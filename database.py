"""
数据库模块 - 会话持久化
支持 PostgreSQL (生产环境) 和 SQLite (本地开发)
使用连接池优化性能
"""
import os
from datetime import datetime
from contextlib import contextmanager

# 设置东八区时区（北京时间）
try:
    from zoneinfo import ZoneInfo
    TZ_BEIJING = ZoneInfo("Asia/Shanghai")
except ImportError:
    # Python < 3.9 使用 pytz
    try:
        import pytz
        TZ_BEIJING = pytz.timezone("Asia/Shanghai")
    except ImportError:
        TZ_BEIJING = None

def get_beijing_time():
    """获取北京时间"""
    if TZ_BEIJING:
        return datetime.now(TZ_BEIJING)
    else:
        # 回退到 UTC+8 计算
        from datetime import timedelta
        return datetime.utcnow() + timedelta(hours=8)

# 判断使用哪种数据库
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgresql")

# ========== 连接池配置 ==========
# PostgreSQL 连接池
_pg_pool = None

# SQLite 连接（单连接复用）
_sqlite_conn = None

if USE_POSTGRES:
    import psycopg2
    from psycopg2 import pool
    from psycopg2.extras import RealDictCursor
    
    def init_connection_pool(min_conn=1, max_conn=10):
        """初始化 PostgreSQL 连接池"""
        global _pg_pool
        if _pg_pool is None:
            try:
                _pg_pool = pool.ThreadedConnectionPool(
                    min_conn,
                    max_conn,
                    DATABASE_URL,
                    cursor_factory=RealDictCursor,
                    connect_timeout=10,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5
                )
                print(f"[DB] PostgreSQL 连接池初始化成功 (min={min_conn}, max={max_conn})")
            except Exception as e:
                print(f"[DB] 连接池初始化失败: {e}")
                raise
        return _pg_pool
    
    def get_pool():
        """获取连接池"""
        global _pg_pool
        if _pg_pool is None:
            _pg_pool = init_connection_pool()
        return _pg_pool
    
    @contextmanager
    def get_db():
        """PostgreSQL 连接上下文管理器（使用连接池，带健康检查）"""
        pg_pool = get_pool()
        conn = None
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                conn = pg_pool.getconn()
                # 健康检查：执行简单查询确认连接有效
                with conn.cursor() as cur:
                    cur.execute('SELECT 1')
                    cur.fetchone()
                yield conn
                return
            except psycopg2.OperationalError as e:
                # 连接失效，关闭并重试
                print(f"[DB] 连接失效，重试 {retry_count + 1}/{max_retries}: {e}")
                if conn:
                    try:
                        pg_pool.putconn(conn, close=True)
                    except:
                        pass
                    conn = None
                retry_count += 1
                if retry_count >= max_retries:
                    raise
            except Exception:
                raise
            finally:
                if conn:
                    try:
                        pg_pool.putconn(conn)
                    except:
                        pass
    
    def close_pool():
        """关闭连接池"""
        global _pg_pool
        if _pg_pool:
            _pg_pool.closeall()
            _pg_pool = None
            print("[DB] PostgreSQL 连接池已关闭")

else:
    import sqlite3
    from threading import Lock
    
    DB_PATH = os.getenv("DB_PATH", "brainstorm.db")
    _sqlite_lock = Lock()
    
    def init_sqlite_connection():
        """初始化 SQLite 连接（单连接复用）"""
        global _sqlite_conn
        if _sqlite_conn is None:
            _sqlite_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _sqlite_conn.row_factory = sqlite3.Row
            print(f"[DB] SQLite 连接初始化成功: {DB_PATH}")
        return _sqlite_conn
    
    @contextmanager
    def get_db():
        """SQLite 连接上下文管理器（单连接 + 线程锁）"""
        global _sqlite_conn
        if _sqlite_conn is None:
            _sqlite_conn = init_sqlite_connection()
        
        with _sqlite_lock:
            try:
                yield _sqlite_conn
            finally:
                pass  # 不关闭连接，保持复用
    
    def close_sqlite():
        """关闭 SQLite 连接"""
        global _sqlite_conn
        if _sqlite_conn:
            _sqlite_conn.close()
            _sqlite_conn = None
            print("[DB] SQLite 连接已关闭")


def init_db():
    """初始化数据库表"""
    print(f"[DB] ========== 开始初始化数据库 ==========")
    print(f"[DB] USE_POSTGRES={USE_POSTGRES}, DATABASE_URL={DATABASE_URL[:30] if DATABASE_URL else 'None'}...")
    
    try:
        with get_db() as db:
            cur = db.cursor()
            
            # 用户表
            print("[DB] 创建 users 表...")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMP,
                    last_active TIMESTAMP
                )
            ''')
            print("[DB] users 表 OK")
            
            # 会话表
            print("[DB] 创建 sessions 表...")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            ''')
            print("[DB] sessions 表 OK")
            
            # 消息表
            print("[DB] 创建 messages 表...")
            if USE_POSTGRES:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        image_url TEXT,
                        created_at TIMESTAMP,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                ''')
            else:
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        image_url TEXT,
                        created_at TIMESTAMP,
                        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                    )
                ''')
            print("[DB] messages 表 OK")
            
            # 创建索引
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_sessions_user 
                ON sessions(user_id, updated_at DESC)
            ''')
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_messages_session 
                ON messages(session_id, created_at)
            ''')
            
            # 访客使用限制表
            print("[DB] 创建 visitor_usage 表...")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS visitor_usage (
                    visitor_id TEXT PRIMARY KEY,
                    usage_date TEXT NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_visitor_usage_date 
                ON visitor_usage(visitor_id, usage_date)
            ''')
            print("[DB] visitor_usage 表 OK")
            
            db.commit()
            print("[DB] ========== 数据库初始化完成 ==========")
    except Exception as e:
        print(f"[DB] 数据库初始化失败: {e}")
        import traceback
        print(traceback.format_exc())
        raise


# ========== 用户操作 ==========

def get_or_create_user(user_id: str):
    """获取或创建用户，更新最后活跃时间"""
    with get_db() as db:
        cur = db.cursor()
        beijing_time = get_beijing_time()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO users (id, created_at, last_active) 
                VALUES (%s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET last_active = %s
            ''', (user_id, beijing_time, beijing_time, beijing_time))
        else:
            cur.execute('''
                INSERT INTO users (id, created_at, last_active) 
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET last_active = ?
            ''', (user_id, beijing_time, beijing_time, beijing_time))
        db.commit()
        return user_id


# ========== 会话操作 ==========

def create_session(user_id: str, title: str = None) -> str:
    """创建新会话"""
    session_id = f"sess_{get_beijing_time().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}"
    beijing_time = get_beijing_time()
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO sessions (id, user_id, title, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s)
            ''', (session_id, user_id, title, beijing_time, beijing_time))
        else:
            cur.execute('''
                INSERT INTO sessions (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, user_id, title, beijing_time, beijing_time))
        db.commit()
    return session_id


def get_user_sessions(user_id: str):
    """获取用户的所有会话"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                SELECT id, title, created_at, updated_at
                FROM sessions
                WHERE user_id = %s
                ORDER BY updated_at DESC
            ''', (user_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        else:
            cur.execute('''
                SELECT id, title, created_at, updated_at
                FROM sessions
                WHERE user_id = ?
                ORDER BY updated_at DESC
            ''', (user_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def get_session_messages(session_id: str):
    """获取会话的所有消息"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                SELECT role, content, image_url, created_at
                FROM messages
                WHERE session_id = %s
                ORDER BY created_at ASC
            ''', (session_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        else:
            cur.execute('''
                SELECT role, content, image_url, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC
            ''', (session_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]


def delete_session(session_id: str):
    """删除会话（级联删除消息）"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('DELETE FROM sessions WHERE id = %s', (session_id,))
        else:
            cur.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
        db.commit()


def update_session_title(session_id: str, title: str):
    """更新会话标题"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                UPDATE sessions SET title = %s, updated_at = %s WHERE id = %s
            ''', (title, get_beijing_time(), session_id))
        else:
            cur.execute('''
                UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?
            ''', (title, get_beijing_time(), session_id))
        db.commit()


# ========== 消息操作 ==========

def add_message(session_id: str, role: str, content: str, image_url: str = None):
    """添加消息到会话"""
    beijing_time = get_beijing_time()
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO messages (session_id, role, content, image_url, created_at)
                VALUES (%s, %s, %s, %s, %s)
            ''', (session_id, role, content, image_url, beijing_time))
            cur.execute('''
                UPDATE sessions SET updated_at = %s WHERE id = %s
            ''', (beijing_time, session_id))
        else:
            cur.execute('''
                INSERT INTO messages (session_id, role, content, image_url, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (session_id, role, content, image_url, beijing_time))
            cur.execute('''
                UPDATE sessions SET updated_at = ? WHERE id = ?
            ''', (beijing_time, session_id))
        db.commit()


def get_session(session_id: str):
    """获取会话信息"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                SELECT id, user_id, title, created_at, updated_at
                FROM sessions
                WHERE id = %s
            ''', (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        else:
            cur.execute('''
                SELECT id, user_id, title, created_at, updated_at
                FROM sessions
                WHERE id = ?
            ''', (session_id,))
            row = cur.fetchone()
            return dict(row) if row else None


# ========== RAG 向量数据库支持 ==========

def init_vector_db():
    """初始化向量数据库表（仅 PostgreSQL）"""
    if not USE_POSTGRES:
        print("[DB] SQLite 模式，跳过向量数据库初始化")
        return  # SQLite 使用 ChromaDB，不需要 pgvector
    
    print("[DB] PostgreSQL 模式: 初始化向量数据库...")
    
    with get_db() as db:
        cur = db.cursor()
        
        # 启用 pgvector 扩展（单独事务）
        try:
            cur.execute('CREATE EXTENSION IF NOT EXISTS vector')
            db.commit()
            print("[DB] pgvector 扩展已启用")
        except Exception as e:
            print(f"[DB] 警告: 启用 pgvector 扩展失败: {e}")
            db.rollback()  # 回滚失败的事务
            # 继续执行，表可能仍然可以创建
        
        # 知识库表
        try:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            db.commit()
            print("[DB] knowledge_bases 表已创建或已存在")
        except Exception as e:
            print(f"[DB] 警告: 创建 knowledge_bases 表失败: {e}")
            db.rollback()
        
        # 文档表
        try:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP
                )
            ''')
            db.commit()
            print("[DB] documents 表已创建或已存在")
        except Exception as e:
            print(f"[DB] 警告: 创建 documents 表失败: {e}")
            db.rollback()
        
        # 向量表
        try:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id SERIAL PRIMARY KEY,
                    session_id TEXT,
                    kb_id TEXT,
                    doc_id TEXT,
                    content TEXT NOT NULL,
                    embedding vector(1536),
                    metadata JSONB,
                    created_at TIMESTAMP
                )
            ''')
            
            # 创建向量索引
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
                ON document_chunks USING ivfflat (embedding vector_cosine_ops)
            ''')
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_document_chunks_kb 
                ON document_chunks(kb_id)
            ''')
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_document_chunks_session 
                ON document_chunks(session_id)
            ''')
            db.commit()
            print("[DB] 向量表和索引已创建")
        except Exception as e:
            print(f"[DB] 警告: 创建向量表失败: {e}")
            db.rollback()
        
        print("[DB] 向量数据库初始化完成")


def create_knowledge_base(user_id: str, name: str, description: str = None) -> str:
    """创建知识库"""
    import uuid
    kb_id = f"kb_{uuid.uuid4().hex[:8]}"
    
    print(f"[DB] 创建知识库: user_id={user_id}, name={name}, kb_id={kb_id}")
    
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            # 确保表存在（防御性编程）
            print("[DB] PostgreSQL 模式: 检查表是否存在")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP
                )
            ''')
            
            beijing_time = get_beijing_time()
            cur.execute('''
                INSERT INTO knowledge_bases (id, user_id, name, description, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (kb_id, user_id, name, description, beijing_time, beijing_time))
        else:
            # SQLite 不支持向量，但支持基础表结构
            print("[DB] SQLite 模式: 检查并创建表")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP
                )
            ''')
            beijing_time = get_beijing_time()
            cur.execute('''
                INSERT INTO knowledge_bases (id, user_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (kb_id, user_id, name, description, beijing_time, beijing_time))
            print(f"[DB] SQLite 插入成功")
        db.commit()
        print(f"[DB] 事务提交成功")
    return kb_id


def get_user_knowledge_bases(user_id: str):
    """获取用户的所有知识库"""
    print(f"[DB] 查询知识库: user_id={user_id}")
    
    with get_db() as db:
        cur = db.cursor()
        try:
            if USE_POSTGRES:
                cur.execute('''
                    SELECT id, name, description, created_at
                    FROM knowledge_bases
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                ''', (user_id,))
                rows = cur.fetchall()
                # RealDictRow 需要显式转换为 dict
                result = [dict(row) for row in rows]
            else:
                cur.execute('''
                    SELECT id, name, description, created_at
                    FROM knowledge_bases
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
                rows = cur.fetchall()
                result = [dict(row) for row in rows]
            print(f"[DB] 查询结果: {len(result)} 条记录")
            return result
        except Exception as e:
            print(f"[DB] 查询失败: {e}")
            import traceback
            print(traceback.format_exc())
            return []  # 表可能不存在


def delete_knowledge_base(kb_id: str, user_id: str):
    """删除知识库"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('DELETE FROM document_chunks WHERE kb_id = %s', (kb_id,))
            cur.execute('DELETE FROM documents WHERE kb_id = %s', (kb_id,))
            cur.execute('DELETE FROM knowledge_bases WHERE id = %s AND user_id = %s', (kb_id, user_id))
        else:
            cur.execute('DELETE FROM documents WHERE kb_id = ?', (kb_id,))
            cur.execute('DELETE FROM knowledge_bases WHERE id = ? AND user_id = ?', (kb_id, user_id))
        db.commit()


def add_document(kb_id: str, doc_id: str, filename: str, content_type: str, chunk_count: int = 0):
    """添加文档记录"""
    beijing_time = get_beijing_time()
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO documents (id, kb_id, filename, content_type, chunk_count, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (doc_id, kb_id, filename, content_type, chunk_count, beijing_time))
        else:
            cur.execute('''
                INSERT INTO documents (id, kb_id, filename, content_type, chunk_count, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (doc_id, kb_id, filename, content_type, chunk_count, beijing_time))
        db.commit()


def get_documents(kb_id: str):
    """获取知识库的所有文档"""
    with get_db() as db:
        cur = db.cursor()
        try:
            if USE_POSTGRES:
                cur.execute('''
                    SELECT id, filename, content_type, chunk_count, created_at
                    FROM documents
                    WHERE kb_id = %s
                    ORDER BY created_at DESC
                ''', (kb_id,))
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            else:
                cur.execute('''
                    SELECT id, filename, content_type, chunk_count, created_at
                    FROM documents
                    WHERE kb_id = ?
                    ORDER BY created_at DESC
                ''', (kb_id,))
                rows = cur.fetchall()
                return [dict(row) for row in rows]
        except:
            return []


def delete_document(doc_id: str):
    """删除文档"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('DELETE FROM documents WHERE id = %s', (doc_id,))
        else:
            cur.execute('DELETE FROM documents WHERE id = ?', (doc_id,))
        db.commit()


def update_knowledge_base(kb_id: str, name: str = None, description: str = None):
    """更新知识库信息"""
    beijing_time = get_beijing_time()
    with get_db() as db:
        cur = db.cursor()
        if name and description:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = %s, description = %s, updated_at = %s
                    WHERE id = %s
                ''', (name, description, beijing_time, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = ?, description = ?, updated_at = ?
                    WHERE id = ?
                ''', (name, description, beijing_time, kb_id))
        elif name:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = %s, updated_at = %s
                    WHERE id = %s
                ''', (name, beijing_time, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = ?, updated_at = ?
                    WHERE id = ?
                ''', (name, beijing_time, kb_id))
        elif description:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET description = %s, updated_at = %s
                    WHERE id = %s
                ''', (description, beijing_time, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET description = ?, updated_at = ?
                    WHERE id = ?
                ''', (description, beijing_time, kb_id))
        db.commit()


# ========== 访客使用限制 ==========

import threading
_usage_lock = threading.Lock()

def get_visitor_usage(visitor_id: str, usage_date: str):
    """获取访客某日的使用记录"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                SELECT usage_count FROM visitor_usage 
                WHERE visitor_id = %s AND usage_date = %s
            ''', (visitor_id, usage_date))
        else:
            cur.execute('''
                SELECT usage_count FROM visitor_usage 
                WHERE visitor_id = ? AND usage_date = ?
            ''', (visitor_id, usage_date))
        row = cur.fetchone()
        if row:
            # RealDictCursor 返回字典，SQLite 返回元组
            return row['usage_count'] if isinstance(row, dict) else row[0]
        return 0

def increment_visitor_usage_db(visitor_id: str, usage_date: str) -> int:
    """原子性增加访客使用次数，返回最新计数"""
    with _usage_lock:
        with get_db() as db:
            cur = db.cursor()
            beijing_time = get_beijing_time()
            
            if USE_POSTGRES:
                # PostgreSQL: 使用 INSERT ... ON CONFLICT 实现原子性 upsert
                cur.execute('''
                    INSERT INTO visitor_usage (visitor_id, usage_date, usage_count, updated_at)
                    VALUES (%s, %s, 1, %s)
                    ON CONFLICT (visitor_id) DO UPDATE SET
                        usage_count = CASE 
                            WHEN visitor_usage.usage_date = %s 
                            THEN visitor_usage.usage_count + 1 
                            ELSE 1 
                        END,
                        usage_date = %s,
                        updated_at = %s
                    RETURNING usage_count
                ''', (visitor_id, usage_date, beijing_time, usage_date, usage_date, beijing_time))
                result = cur.fetchone()
                if result:
                    # RealDictCursor 返回字典
                    new_count = result['usage_count'] if isinstance(result, dict) else result[0]
                else:
                    new_count = 1
            else:
                # SQLite: 先查询，再插入或更新
                cur.execute('''
                    SELECT usage_count FROM visitor_usage 
                    WHERE visitor_id = ?
                ''', (visitor_id,))
                row = cur.fetchone()
                
                if row:
                    # 存在记录，检查日期
                    cur.execute('''
                        SELECT usage_date FROM visitor_usage WHERE visitor_id = ?
                    ''', (visitor_id,))
                    date_row = cur.fetchone()
                    current_date = date_row[0] if date_row else None
                    
                    if current_date == usage_date:
                        # 同一天，计数+1
                        cur.execute('''
                            UPDATE visitor_usage 
                            SET usage_count = usage_count + 1, updated_at = ?
                            WHERE visitor_id = ?
                        ''', (beijing_time, visitor_id))
                        # SQLite 返回元组
                        new_count = row[0] + 1
                    else:
                        # 新的一天，重置计数
                        cur.execute('''
                            UPDATE visitor_usage 
                            SET usage_date = ?, usage_count = 1, updated_at = ?
                            WHERE visitor_id = ?
                        ''', (usage_date, beijing_time, visitor_id))
                        new_count = 1
                else:
                    # 新访客
                    cur.execute('''
                        INSERT INTO visitor_usage (visitor_id, usage_date, usage_count, updated_at)
                        VALUES (?, ?, 1, ?)
                    ''', (visitor_id, usage_date, beijing_time))
                    new_count = 1
            
            db.commit()
            return new_count
