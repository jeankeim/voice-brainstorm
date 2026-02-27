"""
知识库管理模块 - 文档处理和向量存储
支持 ChromaDB (SQLite 本地开发) 和 PostgreSQL pgvector (生产)
"""
import os
import uuid
import json
from typing import List, Dict, Optional
from datetime import datetime

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
    
    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    texts = [c["text"] for c in chunks]
    metadatas = [{**c["metadata"], "doc_id": doc_id} for c in chunks]
    
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
        cur.execute('''
            INSERT INTO document_chunks (kb_id, doc_id, content, embedding, metadata)
            VALUES (%s, %s, %s, %s, %s)
        ''', (kb_id, doc_id, chunk["text"], embedding, json.dumps(metadata)))
    
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


# ========== 统一接口 ==========

def add_document_chunks(kb_id: str, doc_id: str, chunks: List[Dict], embeddings: List[List[float]]):
    """添加文档块到向量数据库"""
    if USE_POSTGRES:
        add_chunks_to_pg(kb_id, doc_id, chunks, embeddings)
    else:
        add_chunks_to_chroma(kb_id, doc_id, chunks, embeddings)


def search_knowledge_base(kb_id: str, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
    """搜索知识库"""
    if USE_POSTGRES:
        return search_pg(kb_id, query_embedding, top_k)
    else:
        return search_chroma(kb_id, query_embedding, top_k)


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
