"""
知识库管理模块 - 文档处理和向量存储
支持 ChromaDB (SQLite 本地开发) 和 PostgreSQL pgvector (生产)
"""
import os
import uuid
import json
from typing import List, Dict, Optional
from datetime import datetime

# 导入北京时间工具
try:
    from database import get_beijing_time
except ImportError:
    # 如果 database 模块不可用，定义本地版本
    try:
        from zoneinfo import ZoneInfo
        TZ_BEIJING = ZoneInfo("Asia/Shanghai")
        def get_beijing_time():
            return datetime.now(TZ_BEIJING)
    except ImportError:
        try:
            import pytz
            TZ_BEIJING = pytz.timezone("Asia/Shanghai")
            def get_beijing_time():
                return datetime.now(TZ_BEIJING)
        except ImportError:
            from datetime import timedelta
            def get_beijing_time():
                return datetime.utcnow() + timedelta(hours=8)

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgresql")

# ChromaDB 配置（本地开发）
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

# 全局 ChromaDB 客户端（延迟初始化）
_chroma_client = None

def get_chroma_client():
    """获取 ChromaDB 客户端（单例）"""
    global _chroma_client
    if _chroma_client is None and not USE_POSTGRES:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    return _chroma_client


def get_or_create_collection(name: str):
    """获取或创建 ChromaDB 集合"""
    client = get_chroma_client()
    if client is None:
        return None
    return client.get_or_create_collection(name=name)


def extract_text_from_file(file_path: str, content_type: str) -> str:
    """从文件中提取文本"""
    text = ""
    
    if content_type == "text/plain" or file_path.endswith(".txt"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    
    elif content_type == "text/markdown" or file_path.endswith(".md"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    
    elif content_type == "application/pdf" or file_path.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() + "\n"
        except ImportError:
            try:
                from PyPDF2 import PdfReader
                reader = PdfReader(file_path)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            except Exception as e:
                print(f"[PDF提取错误] {e}")
    
    elif file_path.endswith(".docx"):
        try:
            from docx import Document
            doc = Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n"
        except ImportError:
            print("[DOCX提取错误] python-docx 未安装")
    
    return text


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """将文本分割成块"""
    try:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", "。", "，", " ", ""]
        )
        return splitter.split_text(text)
    except ImportError:
        # 简单的文本分割回退
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - chunk_overlap
        return chunks


def process_document(file_path: str, filename: str, content_type: str) -> List[Dict]:
    """
    处理文档：提取文本、分块
    
    Returns:
        List[Dict]: 文档块列表，每个块包含 text 和 metadata
    """
    # 提取文本
    text = extract_text_from_file(file_path, content_type)
    
    if not text.strip():
        return []
    
    # 分块
    chunks = split_text(text)
    
    # 构建文档块
    doc_chunks = []
    for i, chunk in enumerate(chunks):
        doc_chunks.append({
            "text": chunk,
            "metadata": {
                "filename": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
                "source": filename
            }
        })
    
    return doc_chunks


def add_chunks_to_chroma(kb_id: str, doc_id: str, chunks: List[Dict], embeddings: List[List[float]]):
    """将文档块添加到 ChromaDB"""
    collection = get_or_create_collection(f"kb_{kb_id}")
    if collection is None:
        return
    
    beijing_time = get_beijing_time().isoformat()
    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    texts = [c["text"] for c in chunks]
    metadatas = [{**c["metadata"], "doc_id": doc_id, "created_at": beijing_time} for c in chunks]
    
    collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas
    )


def search_chroma(kb_id: str, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    """在 ChromaDB 中搜索"""
    collection = get_or_create_collection(f"kb_{kb_id}")
    if collection is None:
        return []
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    
    matches = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            matches.append({
                "text": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0
            })
    
    return matches


def delete_doc_from_chroma(kb_id: str, doc_id: str):
    """从 ChromaDB 删除文档"""
    collection = get_or_create_collection(f"kb_{kb_id}")
    if collection is None:
        return
    
    # 获取所有文档 ID
    results = collection.get()
    if results["ids"]:
        # 过滤出属于该 doc_id 的 chunk
        ids_to_delete = [id for id in results["ids"] if id.startswith(f"{doc_id}_")]
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)


def add_chunks_to_pg(kb_id: str, doc_id: str, chunks: List[Dict], embeddings: List[List[float]]):
    """将文档块添加到 PostgreSQL pgvector"""
    import psycopg2
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        metadata = {**chunk["metadata"], "doc_id": doc_id, "chunk_index": i}
        # 清理 NUL 字符，避免 PostgreSQL 插入错误
        text = chunk["text"].replace('\x00', '')
        cur.execute('''
            INSERT INTO document_chunks (kb_id, doc_id, content, embedding, metadata)
            VALUES (%s, %s, %s, %s, %s)
        ''', (kb_id, doc_id, text, embedding, json.dumps(metadata)))
    
    conn.commit()
    cur.close()
    conn.close()


def search_pg(kb_id: str, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    """在 PostgreSQL pgvector 中搜索"""
    import psycopg2
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute('''
        SELECT content, metadata, embedding <=> %s::vector as distance
        FROM document_chunks
        WHERE kb_id = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    ''', (query_embedding, kb_id, query_embedding, top_k))
    
    matches = []
    for row in cur.fetchall():
        matches.append({
            "text": row[0],
            "metadata": row[1],
            "distance": row[2]
        })
    
    cur.close()
    conn.close()
    return matches


def delete_doc_from_pg(kb_id: str, doc_id: str):
    """从 PostgreSQL 删除文档"""
    import psycopg2
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute('DELETE FROM document_chunks WHERE kb_id = %s AND doc_id = %s', (kb_id, doc_id))
    
    conn.commit()
    cur.close()
    conn.close()


# ========== 混合召回：BM25 关键词检索 ==========

def search_bm25_pg(kb_id: str, query: str, top_k: int = 20) -> List[Dict]:
    """使用 PostgreSQL 全文搜索进行 BM25 检索"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # 使用 PostgreSQL 的全文搜索功能
        # 将查询转换为 tsquery 格式
        cur.execute('''
            SELECT content, metadata, 
                   ts_rank(to_tsvector('chinese', content), 
                           plainto_tsquery('chinese', %s)) as score
            FROM document_chunks
            WHERE kb_id = %s
              AND to_tsvector('chinese', content) @@ plainto_tsquery('chinese', %s)
            ORDER BY score DESC
            LIMIT %s
        ''', (query, kb_id, query, top_k))
        
        matches = []
        for row in cur.fetchall():
            matches.append({
                "text": row["content"],
                "metadata": row["metadata"],
                "score": float(row["score"]),
                "source": "bm25"
            })
        return matches
    except Exception as e:
        print(f"[BM25搜索错误] {e}")
        return []
    finally:
        cur.close()
        conn.close()


def search_bm25_chroma(kb_id: str, query: str, top_k: int = 20) -> List[Dict]:
    """ChromaDB 的 BM25 检索（简单关键词匹配）"""
    collection = get_or_create_collection(f"kb_{kb_id}")
    if collection is None:
        return []
    
    try:
        # 获取所有文档
        results = collection.get(include=["documents", "metadatas"])
        if not results["documents"]:
            return []
        
        # 简单关键词匹配
        query_keywords = set(query.lower().split())
        matches = []
        
        for i, doc in enumerate(results["documents"]):
            if not doc:
                continue
            content_lower = doc.lower()
            score = sum(1 for kw in query_keywords if kw in content_lower)
            
            if score > 0:
                matches.append({
                    "text": doc,
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                    "score": score,
                    "source": "bm25"
                })
        
        # 按分数排序
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]
    except Exception as e:
        print(f"[BM25搜索错误] {e}")
        return []


def search_bm25(kb_id: str, query: str, top_k: int = 20) -> List[Dict]:
    """BM25 关键词检索统一接口"""
    if USE_POSTGRES:
        return search_bm25_pg(kb_id, query, top_k)
    else:
        return search_bm25_chroma(kb_id, query, top_k)


# ========== 统一接口 ==========

def add_document_chunks(kb_id: str, doc_id: str, chunks: List[Dict], embeddings: List[List[float]]):
    """添加文档块到向量数据库"""
    if USE_POSTGRES:
        add_chunks_to_pg(kb_id, doc_id, chunks, embeddings)
    else:
        add_chunks_to_chroma(kb_id, doc_id, chunks, embeddings)


def search_knowledge_base(kb_id: str, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    """搜索知识库（纯向量检索，保持向后兼容）"""
    if USE_POSTGRES:
        return search_pg(kb_id, query_embedding, top_k)
    else:
        return search_chroma(kb_id, query_embedding, top_k)


def search_knowledge_base_hybrid(kb_id: str, query: str, query_embedding: List[float], 
                                   top_k: int = 5, vector_weight: float = 0.5) -> List[Dict]:
    """
    混合召回：向量检索 + BM25 关键词检索
    
    Args:
        kb_id: 知识库 ID
        query: 查询文本
        query_embedding: 查询向量
        top_k: 返回结果数
        vector_weight: 向量检索权重 (0-1)，默认 0.5 表示均等权重
    
    Returns:
        融合排序后的结果列表
    """
    # 1. 向量检索
    vector_results = search_knowledge_base(kb_id, query_embedding, top_k=20)
    for r in vector_results:
        r["source"] = "vector"
        # 将距离转换为分数（距离越小分数越高）
        r["score"] = 1.0 / (1.0 + r.get("distance", 0))
    
    # 2. BM25 关键词检索
    bm25_results = search_bm25(kb_id, query, top_k=20)
    
    # 3. RRF 融合排序 (Reciprocal Rank Fusion)
    k = 60  # RRF 常数
    doc_scores = {}
    
    # 合并所有文档 ID
    all_docs = {}
    
    for rank, doc in enumerate(vector_results):
        doc_id = doc.get("metadata", {}).get("doc_id", "") + "_" + str(doc.get("metadata", {}).get("chunk_index", 0))
        all_docs[doc_id] = doc
        score = vector_weight * (1.0 / (k + rank + 1))
        doc_scores[doc_id] = doc_scores.get(doc_id, 0) + score
    
    for rank, doc in enumerate(bm25_results):
        doc_id = doc.get("metadata", {}).get("doc_id", "") + "_" + str(doc.get("metadata", {}).get("chunk_index", 0))
        all_docs[doc_id] = doc
        score = (1 - vector_weight) * (1.0 / (k + rank + 1))
        doc_scores[doc_id] = doc_scores.get(doc_id, 0) + score
    
    # 按融合分数排序
    sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
    
    # 构建最终结果
    results = []
    for doc_id, score in sorted_docs[:top_k]:
        doc = all_docs[doc_id]
        doc["hybrid_score"] = score
        results.append(doc)
    
    return results


def delete_document_vectors(kb_id: str, doc_id: str):
    """删除文档的向量"""
    if USE_POSTGRES:
        delete_doc_from_pg(kb_id, doc_id)
    else:
        delete_doc_from_chroma(kb_id, doc_id)


def delete_knowledge_base_vectors(kb_id: str):
    """删除整个知识库的向量"""
    if USE_POSTGRES:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute('DELETE FROM document_chunks WHERE kb_id = %s', (kb_id,))
        conn.commit()
        cur.close()
        conn.close()
    else:
        # 删除 ChromaDB 集合
        client = get_chroma_client()
        if client:
            try:
                client.delete_collection(name=f"kb_{kb_id}")
            except:
                pass
