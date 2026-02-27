"""
集中配置管理模块
统一加载和管理所有环境变量与配置项
"""
import os
from dotenv import load_dotenv

# 加载环境变量（只在此处加载一次）
load_dotenv()

# ========== API Keys ==========
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# ========== R2 存储配置 ==========
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "https://pub-58d4a928ab314f6ebcf07239d9efe2a1.r2.dev")

# ========== 数据库配置 ==========
DATABASE_URL = os.getenv("DATABASE_URL")
DB_PATH = os.getenv("DB_PATH", "brainstorm.db")
USE_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgresql")

# ChromaDB 配置（本地开发）
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

# ========== 模型配置 ==========
MODEL_TEXT = os.getenv("MODEL_TEXT", "qwen-plus")
MODEL_VISION = os.getenv("MODEL_VISION", "qwen-vl-plus")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v2")

# ========== 限制配置 ==========
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "10"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "6000"))

# ========== 文件上传限制 ==========
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE", "2097152"))  # 默认 2MB (2 * 1024 * 1024)
ALLOWED_EXTENSIONS = {
    'txt', 'md', 'pdf', 'docx',  # 文档
    'jpg', 'jpeg', 'png', 'gif', 'webp',  # 图片
    'mp3', 'wav', 'webm', 'ogg', 'm4a'  # 音频
}

# ========== HTTP 超时配置（秒）==========
HTTP_TIMEOUT_CHAT = int(os.getenv("HTTP_TIMEOUT_CHAT", "120"))  # 聊天接口
HTTP_TIMEOUT_EMBEDDING = int(os.getenv("HTTP_TIMEOUT_EMBEDDING", "30"))  # 嵌入接口
HTTP_TIMEOUT_GENERAL = int(os.getenv("HTTP_TIMEOUT_GENERAL", "30"))  # 通用接口

# ========== DashScope 配置 ==========
DASHSCOPE_HOST = "dashscope.aliyuncs.com"
DASHSCOPE_CHAT_PATH = "/compatible-mode/v1/chat/completions"
DASHSCOPE_EMBEDDING_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"

# ========== 系统提示词 ==========
SYSTEM_PROMPT = """你是专业的头脑风暴助手，任务是通过深度提问帮助用户完善想法。

重要能力说明：
- 你具备多模态能力，可以直接分析用户上传的图片内容
- 你可以识别图片中的场景、人物、文字、图表、产品等所有可见元素
- 当用户上传图片时，你必须先详细分析图片内容，再基于分析进行头脑风暴引导
- 不要说自己无法查看图片，你确实可以分析图片

工作流程：
1. 用户分享想法或上传图片后，先理解其核心内容，然后提出第一个深入问题引导进一步思考。
2. 如果用户上传了图片，先分析图片内容，再基于图片进行头脑风暴提问。
3. 每次只提一个问题，等用户回答后再继续；问题要具体、有启发性。
4. 问题维度包括：核心动机、目标受众、价值主张、可行性、潜在挑战、差异化优势、实施路径等。
5. 3-5轮问答后，主动告知用户'已收集足够信息，现在为你整理完整总结'，然后生成结构化总结。
6. 用户随时说'总结'、'整理'、'输出'等，立即生成总结。

总结文档格式（Markdown）：

# 想法总结

## 核心想法
[1-2句话概括]

## 目标与愿景
[清晰的目标]

## 目标用户/受众
[用户画像]

## 核心价值
[独特价值]

## 实施路径
[行动计划]

## 潜在挑战与应对
[问题及解决方案]

## 下一步行动
[3-5个可执行项]

注意事项：
- 用中文交流
- 语气亲和专业，像有经验的创业顾问
- 可以分析图片并基于图片内容进行头脑风暴
- 提问有深度，能引发思考
- 总结全面、结构清晰、有可操作性
- 【重要】每次回复必须控制在2000字以内，优先保证核心内容的完整性
- 如内容过多，请精简次要信息，确保在限制内完成回复
- 避免冗长铺垫，直接切入重点"""


def check_r2_configured() -> bool:
    """检查 R2 是否已配置"""
    return all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME])


def check_dashscope_configured() -> bool:
    """检查 DashScope 是否已配置"""
    return bool(DASHSCOPE_API_KEY)


def get_r2_endpoint() -> str:
    """获取 R2 端点 URL"""
    if not R2_ACCOUNT_ID:
        return ""
    return f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def is_allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS
