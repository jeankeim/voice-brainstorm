"""
数据库模块 - 会话持久化
支持 PostgreSQL (生产环境) 和 SQLite (本地开发)
"""
import os
from datetime import datetime
from contextlib import contextmanager

# 判断使用哪种数据库
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgresql")

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    @contextmanager
    def get_db():
        """PostgreSQL 连接上下文管理器"""
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        try:
            yield conn
        finally:
            conn.close()
else:
    import sqlite3
    
    DB_PATH = os.getenv("DB_PATH", "brainstorm.db")
    
    @contextmanager
    def get_db():
        """SQLite 连接上下文管理器"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO users (id, last_active) 
                VALUES (%s, %s)
                ON CONFLICT(id) DO UPDATE SET last_active = %s
            ''', (user_id, datetime.now(), datetime.now()))
        else:
            cur.execute('''
                INSERT INTO users (id, last_active) 
                VALUES (?, ?)
                ON CONFLICT(id) DO UPDATE SET last_active = ?
            ''', (user_id, datetime.now(), datetime.now()))
        db.commit()
        return user_id


# ========== 会话操作 ==========

def create_session(user_id: str, title: str = None) -> str:
    """创建新会话"""
    session_id = f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}"
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO sessions (id, user_id, title)
                VALUES (%s, %s, %s)
            ''', (session_id, user_id, title))
        else:
            cur.execute('''
                INSERT INTO sessions (id, user_id, title)
                VALUES (?, ?, ?)
            ''', (session_id, user_id, title))
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
            ''', (title, datetime.now(), session_id))
        else:
            cur.execute('''
                UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?
            ''', (title, datetime.now(), session_id))
        db.commit()


# ========== 消息操作 ==========

def add_message(session_id: str, role: str, content: str, image_url: str = None):
    """添加消息到会话"""
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO messages (session_id, role, content, image_url)
                VALUES (%s, %s, %s, %s)
            ''', (session_id, role, content, image_url))
            cur.execute('''
                UPDATE sessions SET updated_at = %s WHERE id = %s
            ''', (datetime.now(), session_id))
        else:
            cur.execute('''
                INSERT INTO messages (session_id, role, content, image_url)
                VALUES (?, ?, ?, ?)
            ''', (session_id, role, content, image_url))
            cur.execute('''
                UPDATE sessions SET updated_at = ? WHERE id = ?
            ''', (datetime.now(), session_id))
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
        try:
            # 启用 pgvector 扩展
            cur.execute('CREATE EXTENSION IF NOT EXISTS vector')
            print("[DB] pgvector 扩展已启用")
        except Exception as e:
            print(f"[DB] 警告: 启用 pgvector 扩展失败: {e}")
            # 继续执行，表可能仍然可以创建
        
        # 知识库表
        cur.execute('''
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("[DB] knowledge_bases 表已创建或已存在")
        
        # 文档表
        cur.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                kb_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                chunk_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        print("[DB] documents 表已创建或已存在")
        
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            print("[DB] document_chunks 表已创建或已存在")
            
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
            print("[DB] 向量索引已创建")
        except Exception as e:
            print(f"[DB] 警告: 创建向量表失败: {e}")
        
        db.commit()
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cur.execute('''
                INSERT INTO knowledge_bases (id, user_id, name, description)
                VALUES (%s, %s, %s, %s)
            ''', (kb_id, user_id, name, description))
        else:
            # SQLite 不支持向量，但支持基础表结构
            print("[DB] SQLite 模式: 检查并创建表")
            cur.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_bases (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    kb_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                INSERT INTO knowledge_bases (id, user_id, name, description)
                VALUES (?, ?, ?, ?)
            ''', (kb_id, user_id, name, description))
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
    with get_db() as db:
        cur = db.cursor()
        if USE_POSTGRES:
            cur.execute('''
                INSERT INTO documents (id, kb_id, filename, content_type, chunk_count)
                VALUES (%s, %s, %s, %s, %s)
            ''', (doc_id, kb_id, filename, content_type, chunk_count))
        else:
            cur.execute('''
                INSERT INTO documents (id, kb_id, filename, content_type, chunk_count)
                VALUES (?, ?, ?, ?, ?)
            ''', (doc_id, kb_id, filename, content_type, chunk_count))
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
    with get_db() as db:
        cur = db.cursor()
        if name and description:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = %s, description = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (name, description, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (name, description, kb_id))
        elif name:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (name, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET name = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (name, kb_id))
        elif description:
            if USE_POSTGRES:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET description = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                ''', (description, kb_id))
            else:
                cur.execute('''
                    UPDATE knowledge_bases 
                    SET description = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (description, kb_id))
        db.commit()
