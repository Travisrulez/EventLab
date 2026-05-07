#!/bin/sh
set -e

# Инициализируем базу данных и засеиваем сценарии по умолчанию
echo "[entrypoint] Инициализация базы данных..."
python manage.py init-db

# Если переданы переменные для автосоздания admin-пользователя —
# создаём его при первом запуске (игнорируем ошибку, если уже существует)
if [ -n "$EVENTLAB_ADMIN_USERNAME" ] && [ -n "$EVENTLAB_ADMIN_PASSWORD" ]; then
    echo "[entrypoint] Создание admin-пользователя '${EVENTLAB_ADMIN_USERNAME}'..."
    python manage.py init-admin \
        --username "$EVENTLAB_ADMIN_USERNAME" \
        --password "$EVENTLAB_ADMIN_PASSWORD" || true
fi

# Запускаем команду, переданную в CMD / docker-compose command
case "$1" in
    serve)
        echo "[entrypoint] Запуск сервера на 0.0.0.0:${PORT:-8000}..."
        exec uvicorn app.main:app \
            --host 0.0.0.0 \
            --port "${PORT:-8000}" \
            --proxy-headers \
            --forwarded-allow-ips "*"
        ;;
    *)
        exec python manage.py "$@"
        ;;
esac
