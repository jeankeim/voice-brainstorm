import os
import json
import http.client
import ssl
import uuid
from datetime import datetime
from flask import Flask, render_template, request, Response, stream_with_context
from dotenv import load_dotenv
import boto3
from botocore.config import Config

load_dotenv()

app = Flask(__name__)

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_HOST = "dashscope.aliyuncs.com"
DASHSCOPE_PATH = "/compatible-mode/v1/chat/completions"
MODEL_NAME = os.getenv("QWEN_MODEL", "qwen-plus")

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
        
        # Return the public URL (assuming public bucket or presigned URL)
        public_url = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com/{R2_BUCKET_NAME}/{unique_name}"
        return public_url, None
    except Exception as e:
        return None, str(e)

SYSTEM_PROMPT = """你是专业的头脑风暴助手，任务是通过深度提问帮助用户完善想法。

工作流程：
1. 用户分享想法后，先认可并理解其核心，然后提出第一个深入问题引导进一步思考。
2. 每次只提一个问题，等用户回答后再继续；问题要具体、有启发性。
3. 问题维度包括：核心动机、目标受众、价值主张、可行性、潜在挑战、差异化优势、实施路径等。
4. 3-5轮问答后，主动告知用户'已收集足够信息，现在为你整理完整总结'，然后生成结构化总结。
5. 用户随时说'总结'、'整理'、'输出'等，立即生成总结。

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
- 提问有深度，能引发思考
- 总结全面、结构清晰、有可操作性"""


def call_dashscope_stream(messages):
    """Use http.client to call DashScope API with streaming."""
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": messages,
        "stream": True,
        "temperature": 0.8,
        "max_tokens": 2000,
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

    if not DASHSCOPE_API_KEY:
        return Response(
            b'{"error":"API Key not configured"}',
            status=500,
            content_type="application/json",
        )

    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

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
                        choices = obj.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                # Use ensure_ascii=True so output is pure ASCII
                                out = "data: " + json.dumps({"content": content}) + "\n\n"
                                yield out.encode("ascii")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except Exception as e:
            err_msg = str(e)
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


@app.route("/api/check", methods=["GET"])
def check():
    configured = bool(DASHSCOPE_API_KEY)
    r2_configured = bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET_NAME)
    return Response(
        json.dumps({"configured": configured, "model": MODEL_NAME, "r2_configured": r2_configured}).encode("ascii"),
        content_type="application/json",
    )


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """Upload file to R2 storage."""
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
