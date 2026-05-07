from __future__ import annotations

from . import db
from .repository import create_scenario


WINDOWS_EVENTCREATE_CMD = r'''@echo off
setlocal
for /L %%i in (1,1,{{count}}) do (
  eventcreate /T INFORMATION /ID 1000 /L APPLICATION /SO DiplomaEventLab /D "DiplomaEventLab base event %%i from task {{task_id}}" >NUL 2>&1
  if errorlevel 1 (
    echo failed to write event %%i via eventcreate
  ) else (
    echo written event %%i via eventcreate
  )
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Milliseconds {{delay_ms}}" >NUL 2>&1
)
endlocal'''

WINDOWS_POWERSHELL_EVENTLOG = r'''$source = "DiplomaEventLab"
$logName = "Application"
try {
    if (-not [System.Diagnostics.EventLog]::SourceExists($source)) {
        New-EventLog -LogName $logName -Source $source
    }
} catch {
    Write-Output "Event source creation requires admin rights. Falling back to eventcreate.exe"
}
for ($i = 1; $i -le {{count}}; $i++) {
    try {
        Write-EventLog -LogName $logName -Source $source -EventId 3001 -EntryType Warning -Message "DiplomaEventLab Windows audit-like event $i for task {{task_id}}"
        Write-Output "written event $i via Write-EventLog"
    } catch {
        eventcreate /T WARNING /ID 1001 /L APPLICATION /SO DiplomaEventLab /D "DiplomaEventLab fallback event $i for task {{task_id}}" | Out-Null
        Write-Output "written event $i via eventcreate"
    }
    Start-Sleep -Milliseconds {{delay_ms}}
}'''

WINDOWS_IDS_HTTP_POWERSHELL = r'''$hostName = "{{target_host}}"
$port = {{target_port}}
if ([string]::IsNullOrWhiteSpace($hostName)) { $hostName = "example.com" }
if ($port -le 0) { $port = 80 }
for ($i = 1; $i -le {{count}}; $i++) {
    $url = "http://$hostName`:$port/diploma-eventlab?id=$i&task={{task_id}}"
    try {
        Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3 | Out-Null
        Write-Output "HTTP request $i to $url"
    } catch {
        Write-Output "HTTP request $i failed: $($_.Exception.Message)"
    }
    Start-Sleep -Milliseconds {{delay_ms}}
}'''

WINDOWS_DNS_CMD = r'''@echo off
setlocal
set "DOMAIN={{target_host}}"
if "%DOMAIN%"=="" set "DOMAIN=example.com"
for /L %%i in (1,1,{{count}}) do (
  nslookup diploma-%%i.task-{{task_id}}.%DOMAIN% >NUL 2>&1
  echo dns request %%i for diploma-%%i.task-{{task_id}}.%DOMAIN%
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Milliseconds {{delay_ms}}" >NUL 2>&1
)
endlocal'''

LINUX_SYSLOG_BASH = r'''#!/usr/bin/env bash
set -u
for i in $(seq 1 {{count}}); do
  logger -t DiplomaEventLab "base linux event $i from task {{task_id}}"
  echo "written syslog event $i"
  sleep {{delay_seconds}}
done'''

LINUX_FILE_EVENTS_BASH = r'''#!/usr/bin/env bash
set -u
workdir="/tmp/diploma-eventlab-task-{{task_id}}"
mkdir -p "$workdir"
for i in $(seq 1 {{count}}); do
  file="$workdir/event-$i.txt"
  echo "DiplomaEventLab file event $i" > "$file"
  chmod 640 "$file"
  cat "$file" >/dev/null
  echo "file event $i at $file"
  sleep {{delay_seconds}}
done'''

LINUX_IDS_HTTP_BASH = r'''#!/usr/bin/env bash
set -u
host="{{target_host}}"
port={{target_port}}
[ -z "$host" ] && host="example.com"
[ "$port" -le 0 ] && port=80
for i in $(seq 1 {{count}}); do
  url="http://${host}:${port}/diploma-eventlab?id=${i}&task={{task_id}}"
  if command -v curl >/dev/null 2>&1; then
    curl -m 3 -sS "$url" >/dev/null || true
  elif command -v wget >/dev/null 2>&1; then
    wget -T 3 -q -O /dev/null "$url" || true
  else
    timeout 3 bash -c "cat < /dev/null > /dev/tcp/${host}/${port}" || true
  fi
  echo "network event $i to $url"
  sleep {{delay_seconds}}
done'''

LINUX_DNS_BASH = r'''#!/usr/bin/env bash
set -u
domain="{{target_host}}"
[ -z "$domain" ] && domain="example.com"
for i in $(seq 1 {{count}}); do
  name="diploma-${i}.task-{{task_id}}.${domain}"
  if command -v getent >/dev/null 2>&1; then
    getent hosts "$name" >/dev/null || true
  elif command -v nslookup >/dev/null 2>&1; then
    nslookup "$name" >/dev/null || true
  else
    ping -c 1 -W 1 "$name" >/dev/null || true
  fi
  echo "dns event $i for $name"
  sleep {{delay_seconds}}
done'''


def seed_scenarios(admin_user_id: int | None = None) -> None:
    existing = db.one("SELECT COUNT(*) AS c FROM scenarios")
    if existing and int(existing["c"]) > 0:
        return
    defaults = [
        ("Windows: Application EventLog через eventcreate", "Безопасная генерация событий Application Log штатной утилитой eventcreate.", "windows", "cmd", WINDOWS_EVENTCREATE_CMD),
        ("Windows: PowerShell EventLog", "Создание событий Application Log через PowerShell/Write-EventLog с fallback на eventcreate.", "windows", "powershell", WINDOWS_POWERSHELL_EVENTLOG),
        ("Windows/IDS: HTTP-запросы к тестовому узлу", "Генерация сетевых HTTP-событий для Netflow/IDS/KUMA в лабораторной сети.", "ids", "powershell", WINDOWS_IDS_HTTP_POWERSHELL),
        ("Windows/IDS: DNS-запросы", "Генерация DNS-запросов к тестовому домену для DNS/IDS/KUMA.", "ids", "cmd", WINDOWS_DNS_CMD),
        ("Linux: syslog через logger", "Базовые события в системном журнале Linux через logger.", "linux", "bash", LINUX_SYSLOG_BASH),
        ("Linux: файловая активность", "Создание, изменение прав и чтение файлов в /tmp для событий auditd/EDR/SIEM.", "linux", "bash", LINUX_FILE_EVENTS_BASH),
        ("Linux/IDS: HTTP-запросы к тестовому узлу", "Генерация сетевых HTTP-событий для Netflow/IDS/KUMA в лабораторной сети.", "ids", "bash", LINUX_IDS_HTTP_BASH),
        ("Linux/IDS: DNS-запросы", "Генерация DNS-запросов к тестовому домену для DNS/IDS/KUMA.", "ids", "bash", LINUX_DNS_BASH),
    ]
    for item in defaults:
        create_scenario(*item, created_by=admin_user_id)
