# Three services share one audited runtime, built away from the production host.
FROM python:3.11-slim
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONUNBUFFERED=1 PYTHONPATH=/app TZ=Asia/Shanghai
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates gcc fonts-dejavu-core fonts-liberation && rm -rf /var/lib/apt/lists/*
COPY requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
RUN python -m playwright install --with-deps chromium && python -m patchright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY common /app/common
COPY scripts /app/scripts
COPY launcher /app/launcher
COPY backend-web /app/backend-web
COPY websocket /app/websocket
COPY scheduler /app/scheduler
RUN mkdir -p /app/backend-web/logs /app/websocket/logs /app/scheduler/logs /app/static/uploads /app/backups /app/browser_data
CMD ["python", "backend-web/main.py"]
