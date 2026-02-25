#!/usr/bin/env python3
"""
Voice Brainstorm - Standalone HTTP Server (no Flask)
Uses only Python standard library to avoid encoding issues.
"""

import os
import json
import http.client
import ssl
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs
from pathlib import Path

# Configuration
PORT = int(os.getenv("PORT", "5002"))
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_HOST = "dashscope.aliyuncs.com"
DASHSCOPE_PATH = "/compatible-mode/v1/chat/completions"
MODEL_NAME = os.getenv("QWEN_MODEL", "qwen-plus")

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# System prompt (ASCII-safe Unicode escapes)
SYSTEM_PROMPT = (
    "\u4f60\u662f\u4e00\u4e2a\u4e13\u4e1a\u7684\u5934\u8111\u98ce\u66b4\u52a9\u624b\u3002"
    "\u4f60\u7684\u4efb\u52a1\u662f\u5e2e\u52a9\u7528\u6237\u6df1\u5165\u601d\u8003\u548c\u5b8c\u5584\u4ed6\u4eec\u7684\u60f3\u6cd5\u3002\n\n"
    "\u5de5\u4f5c\u6d41\u7a0b\uff1a\n"
    "1. \u5f53\u7528\u6237\u5206\u4eab\u4e00\u4e2a\u60f3\u6cd5\u65f6\uff0c\u9996\u5148\u7b80\u8981\u8ba4\u53ef\u5e76\u7406\u89e3\u8fd9\u4e2a\u60f3\u6cd5\u7684\u6838\u5fc3\uff0c"
    "\u7136\u540e\u63d0\u51fa\u7b2c\u4e00\u4e2a\u6df1\u5165\u7684\u95ee\u9898\u6765\u5e2e\u52a9\u7528\u6237\u8fdb\u4e00\u6b65\u601d\u8003\u3002\n"
    "2. \u6bcf\u6b21\u53ea\u63d0\u51fa\u4e00\u4e2a\u95ee\u9898\uff0c\u7b49\u5f85\u7528\u6237\u56de\u7b54\u540e\u518d\u63d0\u51fa\u4e0b\u4e00\u4e2a\u3002"
    "\u95ee\u9898\u8981\u5177\u4f53\u3001\u6709\u542f\u53d1\u6027\uff0c\u907f\u514d\u6cdb\u6cdb\u800c\u8c08\u3002\n"
    "3. \u95ee\u9898\u5e94\u8be5\u4ece\u4e0d\u540c\u7ef4\u5ea6\u5c55\u5f00\uff0c\u5305\u62ec\u4f46\u4e0d\u9650\u4e8e\uff1a"
    "\u6838\u5fc3\u52a8\u673a\u3001\u76ee\u6807\u53d7\u4f17\u3001\u6838\u5fc3\u4ef7\u503c\u4e3b\u5f20\u3001\u53ef\u884c\u6027\u3001"
    "\u6f5c\u5728\u6311\u6218\u3001\u5dee\u5f02\u5316\u4f18\u52bf\u3001\u5b9e\u65bd\u8def\u5f84\u7b49\u3002\n"
    "4. \u57283-5\u8f6e\u95ee\u7b54\u540e\uff08\u901a\u5e38\u95ee3-5\u4e2a\u95ee\u9898\uff09\uff0c"
    "\u4e3b\u52a8\u544a\u8bc9\u7528\u6237\u201c\u6211\u5df2\u7ecf\u6536\u96c6\u4e86\u8db3\u591f\u7684\u4fe1\u606f\uff0c"
    "\u73b0\u5728\u4e3a\u4f60\u6574\u7406\u4e00\u4efd\u5b8c\u6574\u7684\u603b\u7ed3\u201d\uff0c\u7136\u540e\u751f\u6210\u7ed3\u6784\u5316\u603b\u7ed3\u3002\n"
    "5. \u5982\u679c\u7528\u6237\u5728\u4efb\u4f55\u65f6\u5019\u8bf4\u201c\u603b\u7ed3\u201d\u3001\u201c\u6574\u7406\u201d\u3001\u201c\u8f93\u51fa\u201d\u7b49\u7c7b\u4f3c\u7684\u8bdd\uff0c"
    "\u7acb\u5373\u751f\u6210\u603b\u7ed3\u3002\n\n"
    "\u603b\u7ed3\u6587\u6863\u5fc5\u987b\u4f7f\u7528\u4ee5\u4e0bMarkdown\u683c\u5f0f\uff1a\n\n"
    "# \u60f3\u6cd5\u603b\u7ed3\n\n"
    "## \u6838\u5fc3\u60f3\u6cd5\n[\u75281-2\u53e5\u8bdd\u7cbe\u70bc\u6982\u62ec\u7528\u6237\u7684\u60f3\u6cd5]\n\n"
    "## \u76ee\u6807\u4e0e\u613f\u666f\n[\u57fa\u4e8e\u8ba8\u8bba\u6574\u7406\u51fa\u6e05\u6670\u7684\u76ee\u6807]\n\n"
    "## \u76ee\u6807\u7528\u6237/\u53d7\u4f17\n[\u660e\u786e\u7684\u7528\u6237\u753b\u50cf]\n\n"
    "## \u6838\u5fc3\u4ef7\u503c\n[\u8fd9\u4e2a\u60f3\u6cd5\u80fd\u5e26\u6765\u4ec0\u4e48\u72ec\u7279\u4ef7\u503c]\n\n"
    "## \u5b9e\u65bd\u8def\u5f84\n[\u5206\u6b65\u9aa4\u7684\u884c\u52a8\u8ba1\u5212]\n\n"
    "## \u6f5c\u5728\u6311\u6218\u4e0e\u5e94\u5bf9\n[\u53ef\u80fd\u9047\u5230\u7684\u95ee\u9898\u53ca\u5efa\u8bae\u7684\u89e3\u51b3\u65b9\u6848]\n\n"
    "## \u4e0b\u4e00\u6b65\u884c\u52a8\n[3-5\u4e2a\u5177\u4f53\u53ef\u6267\u884c\u7684\u884c\u52a8\u9879]\n\n"
    "\u6ce8\u610f\u4e8b\u9879\uff1a\n"
    "- \u7528\u4e2d\u6587\u4ea4\u6d41\n"
    "- \u8bed\u6c14\u4eb2\u548c\u4e13\u4e1a\uff0c\u50cf\u4e00\u4e2a\u6709\u7ecf\u9a8c\u7684\u521b\u4e1a\u987e\u95ee\n"
    "- \u63d0\u95ee\u8981\u6709\u6df1\u5ea6\uff0c\u80fd\u5f15\u53d1\u7528\u6237\u601d\u8003\n"
    "- \u603b\u7ed3\u8981\u5168\u9762\u3001\u7ed3\u6784\u6e05\u6670\u3001\u6709\u53ef\u64cd\u4f5c\u6027"
)


class RequestHandler(BaseHTTPRequestHandler):
    """Custom HTTP request handler with explicit encoding control."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        """Override to avoid encoding issues in logging."""
        pass  # Disable logging to avoid encoding issues

    def send_bytes(self, data, content_type, status=200):
        """Send raw bytes with explicit Content-Length."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self.serve_file(TEMPLATES_DIR / "index.html", "text/html; charset=utf-8")
        elif path == "/api/check":
            data = json.dumps({
                "configured": bool(DASHSCOPE_API_KEY),
                "model": MODEL_NAME
            }).encode("ascii")
            self.send_bytes(data, "application/json")
        elif path.startswith("/static/"):
            file_path = STATIC_DIR / path[8:]
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if mime_type and "css" in path:
                mime_type = "text/css; charset=utf-8"
            elif mime_type and "js" in path:
                mime_type = "application/javascript; charset=utf-8"
            self.serve_file(file_path, mime_type or "application/octet-stream")
        else:
            self.send_error(404)

    def serve_file(self, file_path, content_type):
        """Serve a static file."""
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            self.send_bytes(data, content_type)
        except FileNotFoundError:
            self.send_error(404)

    def do_POST(self):
        """Handle POST requests."""
        if self.path == "/api/chat":
            self.handle_chat()
        else:
            self.send_error(404)

    def handle_chat(self):
        """Handle chat API with SSE streaming."""
        # Read request body
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            req_data = json.loads(body.decode("utf-8"))
        except Exception:
            self.send_bytes(b'{"error":"Invalid JSON"}', "application/json", 400)
            return

        messages = req_data.get("messages", [])

        if not DASHSCOPE_API_KEY:
            self.send_bytes(b'{"error":"API Key not configured"}', "application/json", 500)
            return

        # Prepare messages with system prompt
        full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

        # Send SSE headers
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # Stream from DashScope
        conn = None
        try:
            # Build request payload (ensure_ascii=True for pure ASCII)
            payload = json.dumps({
                "model": MODEL_NAME,
                "messages": full_messages,
                "stream": True,
                "temperature": 0.8,
                "max_tokens": 2000,
            })  # Default ensure_ascii=True

            # Create HTTPS connection
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(DASHSCOPE_HOST, context=ctx)

            headers = {
                "Authorization": "Bearer " + DASHSCOPE_API_KEY,
                "Content-Type": "application/json",
            }

            conn.request("POST", DASHSCOPE_PATH, body=payload.encode("ascii"), headers=headers)
            resp = conn.getresponse()

            if resp.status != 200:
                err = resp.read().decode("utf-8", errors="replace")
                err_line = "data: " + json.dumps({"error": "API error: " + err[:100]}) + "\n\n"
                self.wfile.write(err_line.encode("ascii"))
                self.wfile.flush()
                return

            # Stream response
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
                        self.wfile.write(b"data: [DONE]\n\n")
                        self.wfile.flush()
                        return

                    try:
                        obj = json.loads(data_str)
                        choices = obj.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                # ensure_ascii=True escapes all non-ASCII as \uXXXX
                                out = "data: " + json.dumps({"content": content}) + "\n\n"
                                self.wfile.write(out.encode("ascii"))
                                self.wfile.flush()
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except Exception as e:
            err_msg = str(e).replace('"', "'")[:100]
            err_line = "data: " + json.dumps({"error": err_msg}) + "\n\n"
            try:
                self.wfile.write(err_line.encode("ascii"))
                self.wfile.flush()
            except Exception:
                pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def run_server(port=PORT, use_ssl=False):
    """Run the HTTP server."""
    server_address = ("0.0.0.0", port)

    httpd = HTTPServer(server_address, RequestHandler)

    if use_ssl:
        cert_path = BASE_DIR / "cert.pem"
        key_path = BASE_DIR / "key.pem"
        if cert_path.exists() and key_path.exists():
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert_path), str(key_path))
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
            print("HTTPS server on port %d" % port)
        else:
            print("Missing cert.pem/key.pem for HTTPS")
            return
    else:
        print("HTTP server on port %d" % port)

    print("Open http://localhost:%d in your browser" % port)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.shutdown()


if __name__ == "__main__":
    import sys
    use_ssl = "--ssl" in sys.argv
    run_server(PORT, use_ssl)
