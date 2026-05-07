# Diploma EventLab

Веб-приложение для магистерского дипломного проекта: управляемая генерация лабораторных событий безопасности для Windows, Linux и IDS/KUMA с удалённым запуском через доверенный агент.

## Что реализовано

- FastAPI-веб-приложение на Python.
- SQLite без Docker для простого запуска на Windows/Linux.
- Защищённая авторизация:
  - Argon2id-хеширование паролей;
  - HttpOnly signed session cookie;
  - CSRF-защита HTML-форм;
  - блокировка после 5 неуспешных попыток входа на 10 минут;
  - журнал аудита входов и действий.
- Роли:
  - `admin` — пользователи, сценарии, задания;
  - `operator` — сценарии и задания;
  - `viewer` — просмотр заданий и отчётов.
- Интерфейс на Bootstrap.
- Создание заданий с выбором:
  - Windows / Linux / IDS;
  - сценариев;
  - количества событий;
  - задержки;
  - целевого узла/порта для IDS/KUMA.
- Добавление собственных сценариев через интерфейс.
- Одноразовая ссылка/токен задания.
- Нативные агенты без обязательного Python на целевой машине:
  - `agents/windows_agent.ps1` для Windows;
  - `agents/linux_agent.sh` для Linux.
- Дополнительный Python-агент `agents/python_agent.py`, который можно упаковать в `.exe` через PyInstaller.
- Онлайн-лог через WebSocket.
- История запусков и HTML-отчёт с возможностью печати/сохранения в PDF.

## Безопасная модель выполнения

Приложение демонстрирует удалённое выполнение заданий в контролируемой лабораторной среде. Простое открытие ссылки в браузере не запускает код на компьютере. Для выполнения используется доверенный агент, явно запущенный на целевой машине. Это корректная и защищаемая для диплома модель: сервер управления выдаёт задание, агент получает и исполняет только созданные в системе сценарии.

## Быстрый старт

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux:
source .venv/bin/activate

pip install -r requirements.txt
python manage.py init-db
python manage.py init-admin --username admin --password StrongPassword123
python manage.py serve --host 0.0.0.0 --port 8000
```

Откройте:

```text
http://127.0.0.1:8000
```

Для сетевого запуска укажите реальный адрес сервера в переменной окружения:

```bash
# Linux
export EVENTLAB_BASE_URL=http://192.168.1.10:8000
python manage.py serve --host 0.0.0.0 --port 8000
```

```powershell
# Windows PowerShell
$env:EVENTLAB_BASE_URL="http://192.168.1.10:8000"
python manage.py serve --host 0.0.0.0 --port 8000
```

## Запуск задания на Windows без Python

1. Создайте задание в интерфейсе.
2. Скачайте `windows_agent.ps1` со страницы задания.
3. Выполните команду со страницы задания:

```powershell
powershell -NoProfile -ExecutionPolicy RemoteSigned -File .\windows_agent.ps1 -TaskUrl "http://SERVER:8000/api/agent/tasks/TOKEN"
```

## Запуск задания на Linux без Python

```bash
chmod +x ./linux_agent.sh
./linux_agent.sh "http://SERVER:8000/api/agent/tasks/TOKEN"
```

## Упаковка Python-агента в EXE

На Windows-машине с Python:

```powershell
pip install pyinstaller
pyinstaller --onefile agents\python_agent.py --name eventlab-agent
```

После этого можно запускать:

```powershell
.\dist\eventlab-agent.exe --task-url "http://SERVER:8000/api/agent/tasks/TOKEN"
```

## Переменные сценариев

В скриптах можно использовать:

- `{{count}}` — количество событий;
- `{{delay_ms}}` — задержка в миллисекундах;
- `{{delay_seconds}}` — задержка в секундах для Bash;
- `{{target_host}}` — целевой хост/домен;
- `{{target_port}}` — целевой порт;
- `{{task_id}}` — ID задания;
- `{{scenario_id}}` — ID сценария.

## Рекомендации для дипломного стенда

- Сервер управления: Windows или Linux с Python.
- Целевые узлы: отдельные тестовые Windows/Linux VM.
- KUMA/IDS: подключить сбор Windows Event Log, syslog, DNS/Netflow/HTTP-событий.
- Для защиты описать, что токен задания ограничен временем жизни, не хранится в открытом виде в БД, а агент выполняет только сценарии, созданные авторизованным пользователем.

## Проверка кода

```bash
python -m py_compile app/*.py agents/python_agent.py manage.py
python manage.py init-db
python manage.py init-admin --username admin --password StrongPassword123
python manage.py serve
```

В отдельном терминале можно протестировать Python-агент после создания задания через UI.
