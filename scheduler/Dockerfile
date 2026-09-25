# Scheduler 服务 Dockerfile
# 单阶段构建，直接使用Python源码

# 基础镜像走 docker.io 官方名（由 buildx 的 buildkitd 镜像加速配置拉取，见流水线 BUILDKIT 配置）
FROM python:3.11-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y curl ca-certificates gcc \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 复制项目源码
COPY common /app/common
COPY scripts /app/scripts
COPY scheduler /app/scheduler
COPY launcher /app/launcher

# 使用统一锁文件和哈希校验，禁止构建时漂移依赖版本。
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock

RUN python -m playwright install --with-deps chromium

# 创建日志目录
RUN mkdir -p /app/scheduler/logs

# 暴露端口
EXPOSE 8091

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV TZ=Asia/Shanghai

# 启动服务
CMD ["python", "scheduler/main.py"]
