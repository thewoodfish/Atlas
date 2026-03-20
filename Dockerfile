# ── Atlas API — Railway / Docker deployment ───────────────────────────────────
# Railway injects PORT automatically; config.py reads PORT → DASHBOARD_PORT.
# For local Docker: docker build -t atlas-api . && docker run -p 5000:5000 atlas-api

FROM python:3.11-slim

WORKDIR /app

# System deps — curl for health check only
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer-cached until requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Persistent dirs (SQLite DB + logs)
RUN mkdir -p /data logs

# Always listen on all interfaces so Railway can reach the process
ENV DASHBOARD_HOST=0.0.0.0

# Health check — Railway uses this to decide when the service is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -sf "http://localhost:${PORT:-5000}/health" || exit 1

CMD ["python", "main.py"]
