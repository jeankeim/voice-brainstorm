"""
文本嵌入服务 - 使用 DashScope text-embedding-v2
"""
import json
import http.client
import ssl
from typing import List, Union

from config import (
    DASHSCOPE_API_KEY, DASHSCOPE_HOST, 
    DASHSCOPE_EMBEDDING_PATH, EMBEDDING_MODEL,
    HTTP_TIMEOUT_EMBEDDING
)


def get_embeddings(texts: Union[str, List[str]], max_retries: int = 2) -> List[List[float]]:
    """
    获取文本的向量嵌入
    
    Args:
        texts: 单个文本或文本列表
        max_retries: 最大重试次数
    
    Returns:
        向量列表，每个向量是 1536 维的 float 列表
    """
    if isinstance(texts, str):
        texts = [texts]
    
    if not DASHSCOPE_API_KEY:
        raise ValueError("DASHSCOPE_API_KEY not configured")
    
    for attempt in range(max_retries + 1):
        try:
            payload = json.dumps({
                "model": EMBEDDING_MODEL,
                "input": {
                    "texts": texts
                }
            })
            
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                DASHSCOPE_HOST, 
                context=ctx, 
                timeout=HTTP_TIMEOUT_EMBEDDING
            )
            
            headers = {
                "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            }
            
            conn.request(
                "POST",
                DASHSCOPE_EMBEDDING_PATH,
                body=payload.encode("utf-8"),
                headers=headers
            )
            
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            
            if resp.status != 200:
                error_msg = data.get("message", "Unknown error")
                raise Exception(f"Embedding API error: {error_msg}")
            
            # 提取嵌入向量
            embeddings = data.get("output", {}).get("embeddings", [])
            return [e["embedding"] for e in embeddings]
            
        except Exception as e:
            if attempt == max_retries:
                raise e
            print(f"[Embedding] Retry {attempt + 1}/{max_retries}: {e}")
    
    return []


def get_embedding(text: str) -> List[float]:
    """获取单个文本的向量嵌入"""
    embeddings = get_embeddings([text])
    return embeddings[0] if embeddings else []


# 简单测试
if __name__ == "__main__":
    
    test_texts = ["Hello world", "你好世界"]
    try:
        embeddings = get_embeddings(test_texts)
        print(f"Generated {len(embeddings)} embeddings")
        print(f"First embedding dimension: {len(embeddings[0])}")
    except Exception as e:
        print(f"Error: {e}")
