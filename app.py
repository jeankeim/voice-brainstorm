import os
import json
import http.client
import ssl
import uuid
import io
import wave
from datetime import datetime, timedelta

# 设置东八区时区（北京时间）
try:
    from zoneinfo import ZoneInfo
    TZ_BEIJING = ZoneInfo("Asia/Shanghai")
except ImportError:
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
        return datetime.utcnow() + timedelta(hours=8)
from flask import Flask, render_template, request, Response, stream_with_context, jsonify
import boto3
from botocore.config import Config
from http import HTTPStatus

# 导入集中配置
from config import (
    DASHSCOPE_API_KEY, DASHSCOPE_HOST, DASHSCOPE_CHAT_PATH,
    MODEL_TEXT, MODEL_VISION, MAX_TOKENS,
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME,
    R2_PUBLIC_URL, check_r2_configured, get_r2_endpoint,
    DAILY_LIMIT, MAX_FILE_SIZE, is_allowed_file,
    HTTP_TIMEOUT_CHAT, HTTP_TIMEOUT_GENERAL,
    SYSTEM_PROMPT
)

# 导入结构化日志
from logger import log_info, log_debug, log_warning, log_error, log_api_request, log_rag_search

# DashScope imports
try:
    from dashscope.audio.asr import Recognition
    DASHSCOPE_ASR_AVAILABLE = True
except ImportError:
    DASHSCOPE_ASR_AVAILABLE = False

# 数据库导入
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import (
    init_db, get_or_create_user, create_session, get_user_sessions,
    get_session_messages, delete_session, update_session_title, add_message,
    get_session, create_knowledge_base, get_user_knowledge_bases,
    delete_knowledge_base, add_document, get_documents
)

# RAG 模块导入
from embedding import get_embedding
from knowledge_base import (
    process_document, add_document_chunks, delete_document_vectors,
    delete_knowledge_base_vectors
)
from retrieval import search_knowledge_bases, search_history_sessions

app = Flask(__name__)

# 初始化数据库
init_db()

# 初始化连接池（PostgreSQL 模式）
from database import USE_POSTGRES
if USE_POSTGRES:
    from database import init_connection_pool
    init_connection_pool(min_conn=2, max_conn=20)

# 初始化向量数据库（PostgreSQL 模式）
from database import init_vector_db
init_vector_db()


# 应用关闭时清理资源
@app.teardown_appcontext
def close_db(error):
    """应用上下文结束时无需关闭连接（连接池管理）"""
    pass


import atexit

def cleanup_resources():
    """应用退出时关闭连接池"""
    if USE_POSTGRES:
        from database import close_pool
        close_pool()
    else:
        from database import close_sqlite
        close_sqlite()

atexit.register(cleanup_resources)

def select_model(messages):
    """根据消息内容选择合适模型。
    
    只检查最后一条用户消息是否有图片：
    - 如果有图片，使用 qwen-vl-plus
    - 否则使用 qwen-plus（包括 PDF 文本、普通文本等）
    """
    # 只检查最后一条用户消息
    user_messages = [msg for msg in messages if msg.get("role") == "user"]
    if not user_messages:
        print(f"[模型选择] 无用户消息，使用 {MODEL_TEXT}")
        return MODEL_TEXT
    
    last_user_msg = user_messages[-1]
    content = last_user_msg.get("content", [])
    
    # 检查是否是多模态格式（包含图片）
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "image_url":
                print(f"[模型选择] 最后消息包含多模态图片，使用 {MODEL_VISION}")
                return MODEL_VISION
    
    # 检查是否有 image_url 字段（前端原始格式）
    if last_user_msg.get("image_url"):
        print(f"[模型选择] 最后消息包含 image_url，使用 {MODEL_VISION}")
        return MODEL_VISION
    
    print(f"[模型选择] 最后消息无图片，使用 {MODEL_TEXT}")
    return MODEL_TEXT

# R2 配置已从 config.py 导入

def get_r2_client():
    """Initialize R2 S3-compatible client."""
    if not check_r2_configured():
        return None
    
    endpoint_url = get_r2_endpoint()
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )

def upload_to_r2(file_data, filename, content_type):
    """Upload file to R2 and return public URL."""
    s3 = get_r2_client()
    if not s3 or not R2_BUCKET_NAME:
        return None, "R2 not configured"
    
    try:
        # Generate unique filename
        ext = filename.split('.')[-1] if '.' in filename else ''
        unique_name = f"{get_beijing_time().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}.{ext}" if ext else f"{get_beijing_time().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}"
        
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=unique_name,
            Body=file_data,
            ContentType=content_type
        )
        
        # Return public URL using R2.dev domain
        public_url = f"{R2_PUBLIC_URL}/{unique_name}"
        return public_url, None
    except Exception as e:
        return None, str(e)

# SYSTEM_PROMPT 已从 config.py 导入


def call_dashscope_stream(messages):
    """Use http.client to call DashScope API with streaming."""
    # 根据消息内容自动选择模型
    model = select_model(messages)
    print(f"Using model: {model}")
    
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.8,
        "max_tokens": MAX_TOKENS,
    })  # ensure_ascii=True by default, pure ASCII body

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(DASHSCOPE_HOST, context=ctx, timeout=HTTP_TIMEOUT_CHAT)

    headers = {
        "Authorization": "Bearer " + DASHSCOPE_API_KEY,
        "Content-Type": "application/json",
    }

    conn.request("POST", DASHSCOPE_CHAT_PATH, body=payload.encode("utf-8"), headers=headers)
    resp = conn.getresponse()

    if resp.status != 200:
        err = resp.read().decode("utf-8", errors="replace")
        conn.close()
        raise Exception("API error %d: %s" % (resp.status, err[:200]))

    return conn, resp


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    messages = data.get("messages", [])
    visitor_id = data.get("visitor_id")
    session_id = data.get("session_id")
    kb_ids = data.get("kb_ids", [])  # 启用的知识库 ID 列表
    use_rag = data.get("use_rag", False)  # 是否启用 RAG
    
    # 调试日志
    log_info(f"[RAG] 接收参数: use_rag={use_rag}, kb_ids={kb_ids}, visitor_id={visitor_id}")
    
    # 检查使用限制
    allowed, error_msg = check_visitor_limit(visitor_id)
    if not allowed:
        return Response(
            json.dumps({"error": error_msg, "limit_reached": True}).encode("utf-8"),
            status=429,
            content_type="application/json"
        )

    if not DASHSCOPE_API_KEY:
        return Response(
            b'{"error":"API Key not configured"}',
            status=500,
            content_type="application/json",
        )

    # 保存最后一条用户消息到数据库
    if session_id and messages:
        last_msg = messages[-1]
        if last_msg.get("role") == "user":
            try:
                add_message(
                    session_id=session_id,
                    role="user",
                    content=last_msg.get("content", ""),
                    image_url=last_msg.get("image_url")
                )
                print(f"[数据库] 保存用户消息到会话 {session_id}")
            except Exception as e:
                print(f"[数据库] 保存消息失败: {e}")
    
    # RAG 检索增强
    rag_context = ""
    if use_rag and messages:
        log_api_request("/api/chat", method="POST", use_rag=True, kb_ids=kb_ids)
        last_user_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg.get("content", "")
                break
        
        if last_user_msg:
            try:
                log_rag_search(last_user_msg, kb_ids, 0)
                
                # 知识库检索
                kb_results = []
                if kb_ids:
                    kb_results = search_knowledge_bases(kb_ids, last_user_msg, top_k=5)
                    log_info(f"[RAG] 知识库检索结果: {len(kb_results)} 条", type="rag_results", source="knowledge_base", count=len(kb_results))
                
                # 历史会话检索
                history_results = []
                if visitor_id:
                    history_results = search_history_sessions(visitor_id, last_user_msg, top_k=3)
                    log_info(f"[RAG] 历史会话检索结果: {len(history_results)} 条", type="rag_results", source="history", count=len(history_results))
                
                # 构建上下文
                context_parts = []
                if kb_results:
                    context_parts.append("=== 知识库参考 ===")
                    for i, r in enumerate(kb_results[:3], 1):
                        source = r.get("metadata", {}).get("filename", "未知")
                        context_parts.append(f"[{i}] 来源：{source}")
                        context_parts.append(f"内容：{r['text'][:300]}...")
                        context_parts.append("")
                
                if history_results:
                    context_parts.append("=== 历史对话参考 ===")
                    for i, r in enumerate(history_results[:2], 1):
                        role = "用户" if r["role"] == "user" else "AI"
                        context_parts.append(f"[{i}] {role}：{r['text'][:200]}...")
                        context_parts.append("")
                
                if context_parts:
                    rag_context = "\n".join(context_parts)
                    print(f"[RAG] 上下文构建完成，长度: {len(rag_context)}")
            except Exception as e:
                print(f"[RAG] 检索失败: {e}")

    # Convert messages to qwen-vl format if needed
    converted_messages = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            # Already in multimodal format
            converted_messages.append(msg)
        elif msg.get("role") == "user" and msg.get("image_url"):
            # Convert to qwen-vl multimodal format
            # qwen-vl uses 'image_url' type with 'url' field
            image_url = msg["image_url"]
            print(f"[图片分析] 处理图片消息，URL: {image_url[:80]}...")
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
                print(f"[图片分析] 添加文本内容: {msg['content'][:50]}...")
            content.append({
                "type": "image_url",
                "image_url": {"url": image_url}
            })
            print(f"[图片分析] 已转换为多模态格式，content 长度: {len(content)}")
            converted_messages.append({"role": "user", "content": content})
        else:
            converted_messages.append(msg)

    # 构建系统提示词（融入 RAG 上下文）
    system_content = SYSTEM_PROMPT
    if rag_context:
        system_content = f"""{SYSTEM_PROMPT}

=== 参考信息 ===
{rag_context}
=== 参考信息结束 ===

请基于以上参考信息回答用户的问题。如果参考信息不足以回答问题，请基于你的知识回答。"""
    
    full_messages = [{"role": "system", "content": system_content}] + converted_messages
    
    # Debug: print the messages being sent
    print("Sending messages to API:", json.dumps(full_messages, ensure_ascii=False, indent=2)[:500] + "...")

    def generate():
        conn = None
        full_ai_content = ""  # 收集完整 AI 回复
        try:
            conn, resp = call_dashscope_stream(full_messages)

            buf = b""
            while True:
                # 使用更小的缓冲区 (512字节) 以获得更平滑的流式效果
                chunk = resp.read(512)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line_bytes, buf = buf.split(b"\n", 1)
                    line_str = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line_str or not line_str.startswith("data:"):
                        continue
                    data_str = line_str[5:].strip()
                    if data_str == "[DONE]":
                        # 保存 AI 回复到数据库
                        if session_id and full_ai_content:
                            try:
                                add_message(
                                    session_id=session_id,
                                    role="assistant",
                                    content=full_ai_content
                                )
                                log_info(f"[数据库] 保存 AI 回复到会话 {session_id}", type="db_save")
                            except Exception as e:
                                log_error(f"[数据库] 保存 AI 回复失败: {e}", type="db_save_error")
                        yield b"data: [DONE]\n\n"
                        break
                    try:
                        obj = json.loads(data_str)
                        choices = obj.get("choices", [])
                        if choices:
                            choice = choices[0]
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            finish_reason = choice.get("finish_reason")
                            
                            # 检查生成结束原因
                            if finish_reason:
                                log_debug(f"生成结束原因: {finish_reason}", type="stream_finish")
                            
                            if content:
                                full_ai_content += content  # 收集内容
                                # Use ensure_ascii=True so output is pure ASCII
                                out = "data: " + json.dumps({"content": content}) + "\n\n"
                                yield out.encode("ascii")
                                # 强制刷新缓冲区，确保即时发送
                                import sys
                                sys.stdout.flush()
                    except (json.JSONDecodeError, KeyError, IndexError) as e:
                        log_debug(f"Parse error: {e}", type="parse_error", data=data_str[:100])
                        continue

        except Exception as e:
            import traceback
            err_msg = str(e)
            print("Error in generate:", err_msg)
            print(traceback.format_exc())
            out = "data: " + json.dumps({"error": err_msg}) + "\n\n"
            yield out.encode("ascii")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=120",
        },
    )


# ========== 访客使用限制配置 ==========
# 每日免费使用次数限制
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "10"))
# 访客使用记录: {visitor_id: {"count": int, "date": str(YYYY-MM-DD)}}
visitor_usage = {}

def check_visitor_limit(visitor_id):
    """检查访客是否超出使用限制。"""
    if not visitor_id:
        return False, "缺少访客标识"
    
    today = get_beijing_time().strftime("%Y-%m-%d")
    record = visitor_usage.get(visitor_id)
    
    # 新访客或新的一天
    if not record or record.get("date") != today:
        visitor_usage[visitor_id] = {"count": 0, "date": today}
        record = visitor_usage[visitor_id]
    
    if record["count"] >= DAILY_LIMIT:
        return False, f"今日免费次数已用完（{DAILY_LIMIT}次），请明天再来"
    
    return True, None

def increment_visitor_usage(visitor_id):
    """增加访客使用次数。"""
    if visitor_id and visitor_id in visitor_usage:
        visitor_usage[visitor_id]["count"] += 1
        return visitor_usage[visitor_id]["count"]
    return 0

def get_visitor_remaining(visitor_id):
    """获取访客剩余次数。"""
    today = get_beijing_time().strftime("%Y-%m-%d")
    record = visitor_usage.get(visitor_id)
    
    if not record or record.get("date") != today:
        return DAILY_LIMIT
    
    return max(0, DAILY_LIMIT - record["count"])


@app.route("/api/check", methods=["GET"])
def check():
    configured = bool(DASHSCOPE_API_KEY)
    r2_configured = check_r2_configured()
    return Response(
        json.dumps({
            "configured": configured,
            "model_text": MODEL_TEXT,
            "model_vision": MODEL_VISION,
            "r2_configured": r2_configured,
            "daily_limit": DAILY_LIMIT
        }).encode("ascii"),
        content_type="application/json",
    )


@app.route("/api/usage", methods=["POST"])
def get_usage():
    """获取访客当前使用情况和剩余次数。"""
    data = request.json or {}
    visitor_id = data.get("visitor_id")
    
    if not visitor_id:
        return Response(
            json.dumps({"error": "Missing visitor_id"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    remaining = get_visitor_remaining(visitor_id)
    today = get_beijing_time().strftime("%Y-%m-%d")
    record = visitor_usage.get(visitor_id, {})
    used = record.get("count", 0) if record.get("date") == today else 0
    
    return Response(
        json.dumps({
            "daily_limit": DAILY_LIMIT,
            "used_today": used,
            "remaining": remaining,
            "reset_time": "次日 00:00"
        }).encode("utf-8"),
        content_type="application/json"
    )


@app.route("/api/increment-usage", methods=["POST"])
def increment_usage():
    """增加访客使用次数。"""
    data = request.json or {}
    visitor_id = data.get("visitor_id")
    
    if visitor_id:
        count = increment_visitor_usage(visitor_id)
        remaining = get_visitor_remaining(visitor_id)
        return Response(
            json.dumps({"success": True, "count": count, "remaining": remaining}).encode("utf-8"),
            content_type="application/json"
        )
    
    return Response(
        json.dumps({"error": "Missing visitor_id"}).encode("utf-8"),
        status=400,
        content_type="application/json"
    )


def extract_pdf_text(file_data):
    """Extract text content from PDF file."""
    try:
        import io
        
        # 尝试导入 PyPDF2 或 pypdf
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            try:
                from pypdf import PdfReader
            except ImportError:
                return {
                    "text": "",
                    "pages": 0,
                    "success": False,
                    "error": "PDF 库未安装，请运行: pip install PyPDF2"
                }
        
        pdf_file = io.BytesIO(file_data)
        reader = PdfReader(pdf_file)
        
        text_content = []
        total_pages = len(reader.pages)
        
        print(f"PDF 总页数: {total_pages}")
        
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    text_content.append(f"--- 第 {i+1} 页 ---\n{page_text}")
                    print(f"第 {i+1} 页提取成功，长度: {len(page_text)}")
                else:
                    print(f"第 {i+1} 页无文本内容（可能是扫描件或图片）")
            except Exception as e:
                print(f"提取第 {i+1} 页失败: {e}")
                continue
        
        full_text = "\n\n".join(text_content)
        
        # 如果内容太长，截断并提示
        max_length = 15000  # 约 5000 汉字
        if len(full_text) > max_length:
            full_text = full_text[:max_length] + "\n\n... (内容已截断，仅显示前 15000 字符)"
        
        # 如果没有提取到任何文本，可能是扫描件
        if not full_text.strip():
            return {
                "text": "",
                "pages": total_pages,
                "success": False,
                "error": "无法提取文本，该 PDF 可能是扫描件或图片格式"
            }
        
        return {
            "text": full_text,
            "pages": total_pages,
            "success": True
        }
    except Exception as e:
        print(f"PDF 提取失败: {e}")
        import traceback
        print(traceback.format_exc())
        return {
            "text": "",
            "pages": 0,
            "success": False,
            "error": str(e)
        }


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload file to R2 storage and return public URL."""
    if "file" not in request.files:
        return Response(
            json.dumps({"error": "No file provided"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    file = request.files["file"]
    if file.filename == "":
        return Response(
            json.dumps({"error": "Empty filename"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    # 检查文件扩展名
    if not is_allowed_file(file.filename):
        return Response(
            json.dumps({"error": f"不支持的文件类型。允许的类型: {', '.join(ALLOWED_EXTENSIONS)}"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    # Read file data
    file_data = file.read()
    original_size = len(file_data)
    
    # 检查是否为图片，如果是则压缩
    is_image = file.content_type and file.content_type.startswith('image/')
    if is_image:
        file_data = compress_image(file_data, file.filename)
        compressed_size = len(file_data)
        if original_size != compressed_size:
            log_info(f"图片压缩: {original_size} -> {compressed_size} bytes", 
                    type="image_compress", original_size=original_size, compressed_size=compressed_size)
    
    # 检查文件大小
    if len(file_data) > MAX_FILE_SIZE:
        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
        return Response(
            json.dumps({"error": f"文件大小超过限制（最大 {max_size_mb:.1f}MB）"}).encode("utf-8"),
            status=413,
            content_type="application/json"
        )
    
    content_type = file.content_type or "application/octet-stream"
    
    # Upload to R2
    url, error = upload_to_r2(file_data, file.filename, content_type)
    
    if error:
        return Response(
            json.dumps({"error": error}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )
    
    # 如果是 PDF，提取文本内容
    pdf_content = None
    if file.filename.lower().endswith('.pdf'):
        pdf_content = extract_pdf_text(file_data)
    
    response_data = {
        "url": url,
        "filename": file.filename,
        "size": len(file_data)
    }
    
    if pdf_content:
        response_data["pdf_content"] = pdf_content
    
    return Response(
        json.dumps(response_data).encode("utf-8"),
        content_type="application/json"
    )


@app.route("/api/speech-to-text", methods=["POST"])
def speech_to_text():
    """Convert speech audio to text using DashScope Paraformer."""
    if not DASHSCOPE_ASR_AVAILABLE:
        return Response(
            json.dumps({"error": "DashScope ASR not available. Please install: pip install dashscope>=1.20.0"}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )
    
    if not DASHSCOPE_API_KEY:
        return Response(
            json.dumps({"error": "DASHSCOPE_API_KEY not configured"}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )
    
    if "audio" not in request.files:
        return Response(
            json.dumps({"error": "No audio file provided"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    audio_file = request.files["audio"]
    if audio_file.filename == "":
        return Response(
            json.dumps({"error": "Empty filename"}).encode("utf-8"),
            status=400,
            content_type="application/json"
        )
    
    temp_input = None
    temp_wav = None
    
    try:
        # Read audio data
        audio_data = audio_file.read()
        print(f"收到音频数据: {len(audio_data)} bytes")
        
        # Validate audio data (至少 3KB，约 0.5 秒音频)
        if len(audio_data) < 3000:
            return Response(
                json.dumps({"text": "", "warning": "音频太短，已跳过"}).encode("utf-8"),
                content_type="application/json"
            )
        
        # Save original file
        temp_input = f"/tmp/{uuid.uuid4().hex}_input"
        with open(temp_input, "wb") as f:
            f.write(audio_data)
        
        # Convert to WAV using pydub
        try:
            from pydub import AudioSegment
            
            # Try to load as webm/opus
            audio = AudioSegment.from_file(temp_input, format="webm")
            
            # Convert to 16kHz, mono, 16-bit WAV
            audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
            
            # Export to WAV
            temp_wav = f"/tmp/{uuid.uuid4().hex}.wav"
            audio.export(temp_wav, format="wav")
            print(f"转换后的 WAV 文件: {temp_wav}")
            
        except Exception as convert_err:
            print(f"音频转换失败: {convert_err}")
            return Response(
                json.dumps({"error": f"音频格式转换失败: {str(convert_err)}"}).encode("utf-8"),
                status=500,
                content_type="application/json"
            )
        
        # Import dashscope and set API key
        import dashscope
        dashscope.api_key = DASHSCOPE_API_KEY
        
        # Call DashScope ASR with timeout handling
        try:
            recognition = Recognition(
                model='paraformer-realtime-v2',
                format='wav',
                sample_rate=16000,
                language_hints=['zh', 'en'],
                callback=None
            )
            
            result = recognition.call(temp_wav)
            
            if result.status_code == HTTPStatus.OK:
                sentences = result.get_sentence()
                text = ""
                if isinstance(sentences, list):
                    text = "".join([s.get("text", "") for s in sentences])
                elif isinstance(sentences, dict):
                    text = sentences.get("text", "")
                
                print(f"识别结果: {text}")
                return Response(
                    json.dumps({"text": text}).encode("utf-8"),
                    content_type="application/json"
                )
            else:
                print(f"ASR API 错误: {result.message}")
                return Response(
                    json.dumps({"error": f"语音识别失败: {result.message}"}).encode("utf-8"),
                    status=500,
                    content_type="application/json"
                )
        except Exception as asr_err:
            print(f"ASR 调用异常: {asr_err}")
            return Response(
                json.dumps({"error": f"语音识别服务异常，请稍后重试"}).encode("utf-8"),
                status=500,
                content_type="application/json"
            )
            
    except Exception as e:
        import traceback
        print("Speech recognition error:", str(e))
        print(traceback.format_exc())
        return Response(
            json.dumps({"error": "语音识别处理失败，请重试"}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )
    finally:
        # Clean up temp files - always execute
        for temp_file in [temp_input, temp_wav]:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                    print(f"清理临时文件: {temp_file}")
                except Exception as clean_err:
                    print(f"清理临时文件失败: {clean_err}")


def convert_to_wav(audio_data):
    """Convert audio data to standard WAV format (16kHz, mono, 16-bit)."""
    # If already WAV, return as-is
    if audio_data.startswith(b'RIFF'):
        return audio_data
    
    # For webm/opus from MediaRecorder, we need to use ffmpeg or pydub
    # For now, assume input is PCM or try to handle basic conversion
    # This is a simplified version - in production, use pydub or ffmpeg
    
    # Create WAV header for raw PCM data
    # Assuming input is 16kHz, mono, 16-bit PCM
    sample_rate = 16000
    channels = 1
    sample_width = 2
    
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)
    
    return wav_buffer.getvalue()


def compress_image(image_data: bytes, filename: str, max_size: int = 1920, quality: int = 85) -> bytes:
    """
    压缩图片
    
    Args:
        image_data: 原始图片数据
        filename: 文件名（用于判断格式）
        max_size: 最大边长（像素）
        quality: JPEG 压缩质量（1-95）
    
    Returns:
        压缩后的图片数据
    """
    try:
        from PIL import Image
        import io
        
        # 从 bytes 加载图片
        img = Image.open(io.BytesIO(image_data))
        
        # 转换为 RGB（处理 PNG 透明通道等）
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # 检查是否需要缩放
        width, height = img.size
        if width > max_size or height > max_size:
            # 计算缩放比例
            ratio = min(max_size / width, max_size / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 保存到内存
        output = io.BytesIO()
        
        # 根据原格式选择保存格式
        ext = filename.lower().split('.')[-1] if '.' in filename else 'jpg'
        if ext in ['png']:
            # PNG 使用优化
            img.save(output, format='PNG', optimize=True)
        elif ext in ['webp']:
            # WebP 格式
            img.save(output, format='WEBP', quality=quality, method=6)
        else:
            # 默认 JPEG
            img.save(output, format='JPEG', quality=quality, optimize=True)
        
        compressed_data = output.getvalue()
        
        # 如果压缩后反而更大，返回原图
        if len(compressed_data) >= len(image_data):
            return image_data
        
        return compressed_data
        
    except ImportError:
        log_warning("PIL 未安装，跳过图片压缩", type="image_compress_skip")
        return image_data
    except Exception as e:
        log_error(f"图片压缩失败: {e}", type="image_compress_error")
        return image_data


# ========== 会话管理 API ==========

@app.route("/api/sessions", methods=["POST"])
def create_new_session():
    """创建新会话"""
    data = request.json or {}
    user_id = data.get('visitor_id')
    title = data.get('title', '新对话')
    
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    # 确保用户存在
    get_or_create_user(user_id)
    
    session_id = create_session(user_id, title)
    return jsonify({'id': session_id, 'title': title})


@app.route("/api/sessions", methods=["GET"])
def list_sessions():
    """获取用户的所有会话"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    sessions = get_user_sessions(user_id)
    return jsonify({'sessions': sessions})


@app.route("/api/sessions/<session_id>", methods=["GET"])
def get_session_detail(session_id):
    """获取会话详情和消息"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    # 验证会话所有权
    session = get_session(session_id)
    if not session or session['user_id'] != user_id:
        return jsonify({'error': 'Session not found'}), 404
    
    messages = get_session_messages(session_id)
    return jsonify({
        'id': session_id,
        'title': session.get('title'),
        'messages': messages
    })


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
def delete_session_route(session_id):
    """删除会话"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    # 验证会话所有权
    session = get_session(session_id)
    if not session or session['user_id'] != user_id:
        return jsonify({'error': 'Session not found'}), 404
    
    delete_session(session_id)
    return jsonify({'success': True})


@app.route("/api/sessions/<session_id>/title", methods=["PUT"])
def update_session_title_route(session_id):
    """更新会话标题"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    data = request.json or {}
    title = data.get('title')
    if not title:
        return jsonify({'error': 'Missing title'}), 400
    
    # 验证会话所有权
    session = get_session(session_id)
    if not session or session['user_id'] != user_id:
        return jsonify({'error': 'Session not found'}), 404
    
    update_session_title(session_id, title)
    return jsonify({'success': True})


# ========== 知识库管理 API ==========

@app.route("/api/knowledge-bases", methods=["POST"])
def create_kb():
    """创建知识库"""
    data = request.json or {}
    user_id = data.get('visitor_id')
    name = data.get('name')
    description = data.get('description', '')
    
    print(f"[API] 创建知识库请求: user_id={user_id}, name={name}")
    
    if not user_id:
        print("[API] 错误: 缺少 visitor_id")
        return jsonify({'error': 'Missing visitor_id'}), 400
    if not name:
        print("[API] 错误: 缺少 name")
        return jsonify({'error': 'Missing name'}), 400
    
    try:
        kb_id = create_knowledge_base(user_id, name, description)
        print(f"[API] 知识库创建成功: {kb_id}")
        return jsonify({'id': kb_id, 'name': name, 'description': description})
    except Exception as e:
        import traceback
        print(f"[API] 创建知识库失败: {e}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases", methods=["GET"])
def list_kbs():
    """获取用户的知识库列表"""
    user_id = request.args.get('visitor_id')
    print(f"[API] 获取知识库列表: user_id={user_id}")
    
    if not user_id:
        print("[API] 错误: 缺少 visitor_id")
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    try:
        kbs = get_user_knowledge_bases(user_id)
        print(f"[API] 返回知识库数量: {len(kbs)}")
        return jsonify({'knowledge_bases': kbs})
    except Exception as e:
        import traceback
        print(f"[API] 获取知识库列表失败: {e}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases/<kb_id>", methods=["DELETE"])
def delete_kb(kb_id):
    """删除知识库"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    try:
        # 删除向量数据
        delete_knowledge_base_vectors(kb_id)
        # 删除数据库记录
        delete_knowledge_base(kb_id, user_id)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases/<kb_id>/documents", methods=["POST"])
def upload_document(kb_id):
    """上传文档到知识库"""
    user_id = request.form.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    
    # 检查文件扩展名
    if not is_allowed_file(file.filename):
        return jsonify({'error': f"不支持的文件类型。允许的类型: {', '.join(ALLOWED_EXTENSIONS)}"}), 400
    
    try:
        # 保存临时文件前先检查大小
        file_data = file.read()
        if len(file_data) > MAX_FILE_SIZE:
            max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
            return jsonify({'error': f"文件大小超过限制（最大 {max_size_mb:.1f}MB）"}), 413
        
        # 重置文件指针
        file.seek(0)
        # 保存临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name
        
        # 处理文档
        content_type = file.content_type or 'application/octet-stream'
        chunks = process_document(tmp_path, file.filename, content_type)
        
        # 生成嵌入
        if chunks:
            embeddings = []
            for chunk in chunks:
                emb = get_embedding(chunk['text'])
                embeddings.append(emb)
            
            # 存储到向量数据库
            doc_id = f"doc_{uuid.uuid4().hex[:8]}"
            add_document_chunks(kb_id, doc_id, chunks, embeddings)
            
            # 记录到数据库
            add_document(kb_id, doc_id, file.filename, content_type, len(chunks))
        
        # 清理临时文件
        os.unlink(tmp_path)
        
        return jsonify({
            'success': True,
            'doc_id': doc_id,
            'chunk_count': len(chunks)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases/<kb_id>/documents", methods=["GET"])
def list_documents(kb_id):
    """获取知识库的文档列表"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    try:
        docs = get_documents(kb_id)
        return jsonify({'documents': docs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases/<kb_id>/documents/<doc_id>", methods=["DELETE"])
def delete_document(kb_id, doc_id):
    """删除知识库中的文档"""
    user_id = request.args.get('visitor_id')
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    try:
        # 删除向量数据库中的文档片段
        from knowledge_base import delete_document_vectors
        delete_document_vectors(kb_id, doc_id)
        
        # 删除数据库记录
        from database import delete_document as db_delete_document
        db_delete_document(doc_id)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/knowledge-bases/<kb_id>", methods=["PUT"])
def update_knowledge_base(kb_id):
    """更新知识库信息"""
    data = request.json
    user_id = data.get('visitor_id')
    name = data.get('name')
    description = data.get('description')
    
    if not user_id:
        return jsonify({'error': 'Missing visitor_id'}), 400
    
    try:
        from database import update_knowledge_base as db_update_kb
        db_update_kb(kb_id, name=name, description=description)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== RAG 检索 API ==========

@app.route("/api/rag/search", methods=["POST"])
def rag_search():
    """RAG 检索接口"""
    data = request.json or {}
    query = data.get('query')
    kb_ids = data.get('kb_ids', [])
    user_id = data.get('visitor_id')
    
    if not query:
        return jsonify({'error': 'Missing query'}), 400
    
    try:
        results = {
            'query': query,
            'knowledge_base_results': [],
            'history_results': []
        }
        
        # 知识库检索
        if kb_ids:
            kb_results = search_knowledge_bases(kb_ids, query, top_k=5)
            results['knowledge_base_results'] = kb_results
        
        # 历史会话检索
        if user_id:
            history_results = search_history_sessions(user_id, query, top_k=3)
            results['history_results'] = history_results
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    import sys

    port = int(os.getenv("PORT", "5002"))
    use_ssl = "--ssl" in sys.argv
    if use_ssl:
        cert_path = os.path.join(os.path.dirname(__file__), "cert.pem")
        key_path = os.path.join(os.path.dirname(__file__), "key.pem")
        if os.path.exists(cert_path) and os.path.exists(key_path):
            print("HTTPS mode on port %d" % port)
            app.run(debug=True, host="0.0.0.0", port=port, ssl_context=(cert_path, key_path))
        else:
            print("Missing cert.pem/key.pem")
            sys.exit(1)
    else:
        app.run(debug=False, host="0.0.0.0", port=port)
