import os
import json
import http.client
import ssl
import uuid
import io
import wave
from datetime import datetime
from flask import Flask, render_template, request, Response, stream_with_context
from dotenv import load_dotenv
import boto3
from botocore.config import Config
from http import HTTPStatus

# DashScope imports
try:
    from dashscope.audio.asr import Recognition
    DASHSCOPE_ASR_AVAILABLE = True
except ImportError:
    DASHSCOPE_ASR_AVAILABLE = False

load_dotenv()

app = Flask(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_HOST = "dashscope.aliyuncs.com"
DASHSCOPE_PATH = "/compatible-mode/v1/chat/completions"

# 模型配置：根据场景自动选择
MODEL_TEXT = "qwen-plus"           # 纯文本对话
MODEL_VISION = "qwen-vl-plus"      # 图片分析

def select_model(messages):
    """根据消息内容选择合适模型。
    
    如果有图片消息，使用 qwen-vl-plus
    否则使用 qwen-plus
    """
    for msg in messages:
        if msg.get("role") == "user":
            content = msg.get("content", [])
            # 检查是否是多模态格式（包含图片）
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return MODEL_VISION
            # 检查是否有 image_url 字段
            if msg.get("image_url"):
                return MODEL_VISION
    return MODEL_TEXT

# Cloudflare R2 Configuration
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

def get_r2_client():
    """Initialize R2 S3-compatible client."""
    if not all([R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY]):
        return None
    
    endpoint_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
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
        unique_name = f"{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}.{ext}" if ext else f"{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}"
        
        s3.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=unique_name,
            Body=file_data,
            ContentType=content_type
        )
        
        # Return public URL using R2.dev domain
        public_url = f"https://pub-58d4a928ab314f6ebcf07239d9efe2a1.r2.dev/{unique_name}"
        return public_url, None
    except Exception as e:
        return None, str(e)

SYSTEM_PROMPT = """你是专业的头脑风暴助手，任务是通过深度提问帮助用户完善想法。

能力说明：
- 你可以直接分析用户上传的图片内容，包括图片中的场景、人物、文字、图表等
- 结合图片内容进行针对性的头脑风暴引导

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
- 每次回复控制在1500字以内，保持简洁有力"""


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
        "max_tokens": 4000,
    })  # ensure_ascii=True by default, pure ASCII body

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(DASHSCOPE_HOST, context=ctx)

    headers = {
        "Authorization": "Bearer " + DASHSCOPE_API_KEY,
        "Content-Type": "application/json",
    }

    conn.request("POST", DASHSCOPE_PATH, body=payload.encode("utf-8"), headers=headers)
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

    # Convert messages to qwen-vl format if needed
    converted_messages = []
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            # Already in multimodal format
            converted_messages.append(msg)
        elif msg.get("role") == "user" and msg.get("image_url"):
            # Convert to qwen-vl multimodal format
            # qwen-vl uses 'image_url' type with 'url' field
            content = []
            if msg.get("content"):
                content.append({"type": "text", "text": msg["content"]})
            content.append({
                "type": "image_url",
                "image_url": {"url": msg["image_url"]}
            })
            converted_messages.append({"role": "user", "content": content})
        else:
            converted_messages.append(msg)

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + converted_messages
    
    # Debug: print the messages being sent
    print("Sending messages to API:", json.dumps(full_messages, ensure_ascii=False, indent=2))

    def generate():
        conn = None
        try:
            conn, resp = call_dashscope_stream(full_messages)

            buf = b""
            while True:
                chunk = resp.read(4096)
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
                        yield b"data: [DONE]\n\n"
                        break
                    try:
                        obj = json.loads(data_str)
                        print("Received chunk:", obj)  # Debug
                        choices = obj.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            print("Content:", content)  # Debug
                            if content:
                                # Use ensure_ascii=True so output is pure ASCII
                                out = "data: " + json.dumps({"content": content}) + "\n\n"
                                print("Yielding:", out)  # Debug
                                yield out.encode("ascii")
                    except (json.JSONDecodeError, KeyError, IndexError) as e:
                        print("Parse error:", e, "data:", data_str[:100])  # Debug
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
        },
    )


# ========== 访客使用限制配置 ==========
# 每日免费使用次数限制
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "20"))
# 访客使用记录: {visitor_id: {"count": int, "date": str(YYYY-MM-DD)}}
visitor_usage = {}

def check_visitor_limit(visitor_id):
    """检查访客是否超出使用限制。"""
    if not visitor_id:
        return False, "缺少访客标识"
    
    today = datetime.now().strftime("%Y-%m-%d")
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
    today = datetime.now().strftime("%Y-%m-%d")
    record = visitor_usage.get(visitor_id)
    
    if not record or record.get("date") != today:
        return DAILY_LIMIT
    
    return max(0, DAILY_LIMIT - record["count"])


@app.route("/api/check", methods=["GET"])
def check():
    configured = bool(DASHSCOPE_API_KEY)
    r2_configured = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)
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
    today = datetime.now().strftime("%Y-%m-%d")
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
    
    # Read file data
    file_data = file.read()
    content_type = file.content_type or "application/octet-stream"
    
    # Upload to R2
    url, error = upload_to_r2(file_data, file.filename, content_type)
    
    if error:
        return Response(
            json.dumps({"error": error}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )
    
    return Response(
        json.dumps({
            "url": url,
            "filename": file.filename,
            "size": len(file_data)
        }).encode("utf-8"),
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
    
    try:
        # Read audio data
        audio_data = audio_file.read()
        print(f"收到音频数据: {len(audio_data)} bytes")
        
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
        
        # Call DashScope ASR
        recognition = Recognition(
            model='paraformer-realtime-v2',
            format='wav',
            sample_rate=16000,
            language_hints=['zh', 'en'],
            callback=None
        )
        
        result = recognition.call(temp_wav)
        
        # Clean up temp files
        try:
            os.remove(temp_input)
            os.remove(temp_wav)
        except:
            pass
        
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
            return Response(
                json.dumps({"error": f"ASR failed: {result.message}"}).encode("utf-8"),
                status=500,
                content_type="application/json"
            )
            
    except Exception as e:
        import traceback
        print("Speech recognition error:", str(e))
        print(traceback.format_exc())
        return Response(
            json.dumps({"error": str(e)}).encode("utf-8"),
            status=500,
            content_type="application/json"
        )


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
