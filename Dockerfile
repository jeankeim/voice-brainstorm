FROM python:3.11-slim

# 安装系统依赖（包括 ffmpeg 和编译工具）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        gcc \
        g++ \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制 requirements 并安装依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 使用环境变量 PORT（Zeabur/Render 等平台要求）
ENV PORT=8080
EXPOSE 8080

# 使用 Gunicorn 运行应用
CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-8080} --timeout 120 --keep-alive 5 app:app"]
