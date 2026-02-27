# 构建阶段
FROM python:3.11-slim as builder

WORKDIR /app

# 安装编译依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制并安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt && \
    pip cache purge

# 运行阶段
FROM python:3.11-slim

# 只安装运行时必需的系统依赖（ffmpeg）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 从构建阶段复制 Python 包
COPY --from=builder /root/.local /root/.local

# 复制应用代码（排除不必要的文件）
COPY app.py database.py embedding.py knowledge_base.py retrieval.py ./
COPY templates/ ./templates/
COPY static/ ./static/

# 设置环境变量
ENV PATH=/root/.local/bin:$PATH
ENV PORT=8080
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# 使用 Gunicorn 运行应用（减少 worker 数量节省内存）
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-8080} --timeout 120 --keep-alive 5 app:app"]
