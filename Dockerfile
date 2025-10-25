# syntax=docker/dockerfile:1.4
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 拷贝依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --upgrade pip

RUN pip install numpy && pip install -r requirements.txt

# 拷贝项目文件
COPY . .

# 设置默认端口
EXPOSE 5000

# 启动服务
CMD ["python", "app.py"]