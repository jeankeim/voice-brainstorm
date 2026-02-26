FROM python:3.11-slim

# 安装 ffmpeg（用于音频格式转换）
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 使用环境变量 PORT（Zeabur/Render 等平台要求）
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "gunicorn -w 2 -b 0.0.0.0:${PORT:-8080} app:app"]
