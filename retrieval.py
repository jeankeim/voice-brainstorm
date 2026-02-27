"""
检索模块 - 整合知识库和历史会话检索
"""
import os
from typing import List, Dict, Optional

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

from embedding import get_embedding
from knowledge_base import search_knowledge_base
from database import get_session_messages, USE_POSTGRES


def search_knowledge_bases(kb_ids: List[str], query: str, top_k: int = 5) -> List[Dict]:
    """
    在多个知识库中检索相关内容
    
    Args:
        kb_ids: 知识库 ID 列表
        query: 查询文本
        top_k: 每个知识库返回的最大结果数
    
    Returns:
        检索结果列表，按相关性排序
    """
    if not kb_ids:
        return []
    
    # 获取查询向量
    query_embedding = get_embedding(query)
    if not query_embedding:
        return []
    
    all_results = []
    for kb_id in kb_ids:
        try:
            results = search_knowledge_base(kb_id, query_embedding, top_k)
            for r in results:
                r["kb_id"] = kb_id
                r["source"] = "knowledge_base"
            all_results.extend(results)
        except Exception as e:
            print(f"[检索错误] 知识库 {kb_id}: {e}")
    
    # 按相似度排序（距离越小越相关）
    all_results.sort(key=lambda x: x.get("distance", float('inf')))
    
    return all_results[:top_k * len(kb_ids)]


def search_history_sessions(user_id: str, query: str, top_k: int = 3) -> List[Dict]:
    """
    检索用户历史会话中的相关内容
    
    注意：当前实现是基于关键词的简单匹配
    未来可以改为向量检索（需要将历史消息也存入向量数据库）
    
    Args:
        user_id: 用户 ID
        query: 查询文本
        top_k: 返回的最大结果数
    
    Returns:
        相关历史消息列表
    """
    # 获取用户的所有会话
    from database import get_user_sessions
    sessions = get_user_sessions(user_id)
    
    if not sessions:
        return []
    
    # 提取查询关键词（简单分词）
    query_keywords = set(query.lower().split())
    
    matches = []
    for session in sessions:
        session_id = session["id"]
        messages = get_session_messages(session_id)
        
        # 计算相关性分数（基于关键词匹配）
        for msg in messages:
            content = msg.get("content", "").lower()
            score = sum(1 for kw in query_keywords if kw in content)
            
            if score > 0:
                matches.append({
                    "text": msg["content"],
                    "role": msg["role"],
                    "session_id": session_id,
                    "session_title": session.get("title", "未命名会话"),
                    "created_at": msg.get("created_at"),
                    "score": score,
                    "source": "history"
                })
    
    # 按分数排序
    matches.sort(key=lambda x: x["score"], reverse=True)
    
    return matches[:top_k]


def build_rag_context(
    query: str,
    kb_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    kb_top_k: int = 5,
    history_top_k: int = 3
) -> Dict:
    """
    构建 RAG 上下文
    
    Args:
        query: 用户查询
        kb_ids: 启用的知识库 ID 列表
        user_id: 用户 ID（用于历史检索）
        kb_top_k: 知识库检索数量
        history_top_k: 历史会话检索数量
    
    Returns:
        包含检索结果的字典
    """
    context = {
        "query": query,
        "knowledge_base_results": [],
        "history_results": [],
        "context_text": ""
    }
    
    # 知识库检索
    if kb_ids:
        kb_results = search_knowledge_bases(kb_ids, query, kb_top_k)
        context["knowledge_base_results"] = kb_results
    
    # 历史会话检索
    if user_id:
        history_results = search_history_sessions(user_id, query, history_top_k)
        context["history_results"] = history_results
    
    # 构建上下文文本
    context_parts = []
    
    if context["knowledge_base_results"]:
        context_parts.append("以下是与用户问题相关的知识库内容：")
        for i, r in enumerate(context["knowledge_base_results"], 1):
            source = r.get("metadata", {}).get("filename", "未知来源")
            context_parts.append(f"[{i}] 来源：{source}")
            context_parts.append(f"内容：{r['text'][:500]}...")  # 限制长度
            context_parts.append("")
    
    if context["history_results"]:
        context_parts.append("以下是用户的历史相关对话：")
        for i, r in enumerate(context["history_results"], 1):
            role = "用户" if r["role"] == "user" else "AI"
            context_parts.append(f"[{i}] {role}：{r['text'][:300]}...")
            context_parts.append("")
    
    context["context_text"] = "\n".join(context_parts)
    
    return context


def format_rag_prompt(system_prompt: str, rag_context: Dict, user_message: str) -> str:
    """
    格式化 RAG 增强的提示词
    
    Args:
        system_prompt: 原始系统提示词
        rag_context: RAG 上下文
        user_message: 用户消息
    
    Returns:
        格式化后的完整提示词
    """
    if not rag_context["context_text"]:
        # 没有检索结果，使用原始提示词
        return f"{system_prompt}\n\n用户：{user_message}"
    
    enhanced_prompt = f"""{system_prompt}

=== 参考信息 ===
{rag_context['context_text']}
=== 参考信息结束 ===

请基于以上参考信息回答用户的问题。如果参考信息不足以回答问题，请基于你的知识回答。

用户：{user_message}"""
    
    return enhanced_prompt


# 测试
if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
    # 测试检索
    test_query = "什么是机器学习"
    
    # 测试知识库检索（如果有知识库）
    # results = search_knowledge_bases(["kb_test"], test_query)
    # print(f"知识库结果: {len(results)}")
    
    # 测试历史检索
    # results = search_history_sessions("test_user", test_query)
    # print(f"历史结果: {len(results)}")
