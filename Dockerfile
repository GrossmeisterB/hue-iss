FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/

RUN bash scripts/vendor.sh

RUN useradd -u 1027 -m appuser && \
    mkdir -p /data && \
    chown -R appuser:appuser /data /app

USER appuser

EXPOSE 5057

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:5057/healthz || exit 1

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5057", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "app.app:create_app()"]
