# ── Stage 1: зависимости ──────────────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Stage 2: финальный образ ─────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Создаём непривилегированного пользователя
RUN addgroup --system eventlab && adduser --system --ingroup eventlab eventlab

# Копируем установленные пакеты из предыдущего этапа
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Копируем исходный код
COPY --chown=eventlab:eventlab . .

# Директория для SQLite базы данных (монтируется как volume)
RUN mkdir -p /data && chown eventlab:eventlab /data

COPY --chown=eventlab:eventlab docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER eventlab

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
