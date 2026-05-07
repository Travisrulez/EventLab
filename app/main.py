from __future__ import annotations

import base64
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Annotated
from unittest import runner

from fastapi import Depends, FastAPI, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER

from . import db
from .config import get_settings
from .repository import (
    add_task_log,
    audit,
    create_agent_run,
    create_scenario,
    create_task,
    create_user,
    finish_agent_run,
    get_scenario,
    get_task,
    get_task_by_token,
    get_user,
    get_user_by_username,
    list_agent_runs,
    list_audit,
    list_scenarios,
    list_tasks,
    list_users,
    set_task_status,
    task_logs,
    task_scenarios,
    update_login_failure,
    update_login_success,
    update_scenario,
)
from .security import csrf_token, generate_token, iso, parse_iso, safe_text, token_expiry, utcnow, verify_password
from .seed import seed_scenarios
from .ws import manager

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
settings = get_settings()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
HOST_RE = re.compile(r"^[A-Za-z0-9_.:-]{0,255}$")


def create_app() -> FastAPI:
    db.init_db()
    seed_scenarios()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        https_only=settings.cookie_secure,
        same_site="lax",
        max_age=60 * 60 * 8,
    )
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    register_routes(app)
    return app


def flash(request: Request, message: str, category: str = "info") -> None:
    items = request.session.get("flash", [])
    items.append({"message": message, "category": category})
    request.session["flash"] = items


def pop_flash(request: Request) -> list[dict]:
    items = request.session.get("flash", [])
    request.session["flash"] = []
    return items


def get_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = csrf_token()
        request.session["csrf"] = token
    return token


def assert_csrf(request: Request, value: str) -> None:
    if not value or value != request.session.get("csrf"):
        raise HTTPException(status_code=400, detail="CSRF token mismatch")


def current_user(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = get_user(int(uid))
    if not user or not int(user["is_active"]):
        request.session.clear()
        return None
    return user


def require_login(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="login required")
    return user


def require_role(*roles: str):
    def dep(request: Request):
        user = require_login(request)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="not enough permissions")
        return user
    return dep


def render(request: Request, name: str, context: dict | None = None) -> HTMLResponse:
    user = current_user(request)
    ctx = {
        "request": request,
        "user": user,
        "csrf": get_csrf(request),
        "flashes": pop_flash(request),
        "app_name": settings.app_name,
        "base_url": settings.base_url,
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(request, name, ctx)


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=HTTP_303_SEE_OTHER)


def validate_host(host: str) -> str:
    host = (host or "").strip()
    if not HOST_RE.match(host):
        raise HTTPException(status_code=400, detail="target_host содержит недопустимые символы")
    return host


def render_script(script: str, task, scenario) -> str:
    delay_ms = int(task["delay_ms"])
    replacements = {
        "{{task_id}}": str(task["id"]),
        "{{count}}": str(int(task["event_count"])),
        "{{delay_ms}}": str(delay_ms),
        "{{delay_seconds}}": f"{delay_ms / 1000:.3f}",
        "{{target_host}}": str(task["target_host"] or ""),
        "{{target_port}}": str(int(task["target_port"] or 0)),
        "{{scenario_id}}": str(scenario["id"]),
    }
    out = script
    for key, value in replacements.items():
        out = out.replace(key, value)
    return out


def task_token_from_session(request: Request, task_id: int) -> str | None:
    return request.session.get(f"task_token_{task_id}")



def b64_utf8(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")

async def read_agent_json(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}

    last_error = None

    for encoding in ("utf-8-sig", "utf-8", "cp866", "cp1251", "utf-16", "utf-16le"):
        try:
            text = raw.decode(encoding)
            return json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc

    try:
        text = raw.decode("utf-8", errors="replace")
        return json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=f"Invalid agent JSON body: {safe_text(last_error)}")


def build_windows_bundle(task, scenarios: list) -> str:
    lines = [
        "param()",
        "$ErrorActionPreference = 'Continue'",
        f"$TaskUrl = '{settings.base_url}/api/agent/tasks/{'{TOKEN_PLACEHOLDER}'}'",
    ]
    return ""


def build_windows_bundle_for_token(token: str, task, scenarios: list) -> str:
    parts = [
        "# Diploma EventLab Windows execution bundle",
        "$ErrorActionPreference = 'Continue'",
        f"$TaskUrl = '{settings.base_url}/api/agent/tasks/{token}'",
        "function Invoke-EventLabJsonPost($Url, $Payload) {",
        "  $json = $Payload | ConvertTo-Json -Depth 8 -Compress",
        "  $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($json)",
        "  return Invoke-RestMethod -Method Post -Uri $Url -ContentType 'application/json; charset=utf-8' -Body $bytes",
        "}",
        "function Post-Json($Suffix, $Payload) {",
        "  try {",
        "    $json = $Payload | ConvertTo-Json -Depth 8 -Compress",
        "    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($json)",
        "    Invoke-RestMethod -Method Post -Uri ($TaskUrl + '/' + $Suffix) -ContentType 'application/json; charset=utf-8' -Body $bytes | Out-Null",
        "  } catch {",
        "    Write-Host ('[agent-log-failed] ' + $_.Exception.Message)",
        "  }",
        "}",
        "$runId = 0",
        "$osName = 'Windows'",
        "try {",
        "  $cv = Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'",
        "  $edition = [string]$cv.EditionID",
        "  $build = [string]$cv.CurrentBuildNumber",
        "  $display = [string]$cv.DisplayVersion",
        "  if ([string]::IsNullOrWhiteSpace($display)) { $display = [string]$cv.ReleaseId }",
        "  $osName = ('Windows Edition={0} Build={1} Version={2}' -f $edition, $build, $display)",
        "} catch { $osName = 'Windows' }",
        "try { $r = Invoke-EventLabJsonPost -Url ($TaskUrl + '/start') -Payload @{hostname=$env:COMPUTERNAME; os_name=$osName; agent_version='windows-bundle-1.2-cleanlog'}; $runId = [int]$r.run_id } catch { Write-Host ('start failed: ' + $_.Exception.Message) }",
        "Post-Json 'logs' @{level='info'; message='Windows bundle started'}",
    ]
    for s in scenarios:
        runner = s["runner"]
        if runner not in {"powershell", "cmd"}:
            parts.append(f"Post-Json 'logs' @{{level='warning'; message='Skipped unsupported runner {runner} for Windows'}}")
            continue
        script = render_script(s["script_body"], task, s)
        if runner == "cmd":
            script = "@echo off\r\nchcp 65001 >NUL 2>&1\r\n" + script
        encoded = b64_utf8(script)
        ext = "ps1" if runner == "powershell" else "cmd"
        parts.extend([
            f"$scenarioNameBytes = [Convert]::FromBase64String('{b64_utf8(safe_text(s['name']))}')",
            "$scenarioName = [System.Text.Encoding]::UTF8.GetString($scenarioNameBytes)",
            "Post-Json 'logs' @{level='info'; message=('Scenario started: ' + $scenarioName)}",
            f"$scriptBytes = [Convert]::FromBase64String('{encoded}')",
            "$scriptText = [Text.Encoding]::UTF8.GetString($scriptBytes)",
            f"$scriptFile = Join-Path $env:TEMP ('eventlab-{int(s['id'])}-' + [guid]::NewGuid().ToString() + '.{ext}')",
            "$scriptEncoding = [System.Text.UTF8Encoding]::new($false)",
            "[System.IO.File]::WriteAllText($scriptFile, $scriptText, $scriptEncoding)",
        ])
        if runner == "powershell":
            command = 'powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "$scriptFile"'
        else:
            command = 'cmd.exe /c "$scriptFile"'
        parts.extend([
            "try {",
            f"  $output = & {command} 2>&1",
            "  $exit = $LASTEXITCODE",
            "  foreach ($line in $output) { if ($null -ne $line -and $line.ToString().Trim().Length -gt 0) { Post-Json 'logs' @{level='info'; message=$line.ToString()} } }",
            "  if ($exit -eq $null) { $exit = 0 }",
            "  if ($exit -eq 0) { Post-Json 'logs' @{level='success'; message='Scenario completed'} } else { $global:HadErrors = $true; Post-Json 'logs' @{level='error'; message=('Scenario exit code ' + $exit)} }",
            "} catch { Post-Json 'logs' @{level='error'; message=$_.Exception.Message}; $global:HadErrors = $true }",
            "Remove-Item -Path $scriptFile -Force -ErrorAction SilentlyContinue",
        ])
    parts.extend([
        "if ($global:HadErrors) { $finalStatus='failed' } else { $finalStatus='completed' }",
        "Post-Json 'finish' @{run_id=$runId; status=$finalStatus}",
        "Write-Host ('Diploma EventLab finished with status=' + $finalStatus)",
    ])
    return "\n".join(parts) + "\n"


def sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def build_linux_bundle_for_token(token: str, task, scenarios: list) -> str:
    parts = [
        "#!/usr/bin/env bash",
        "set +e",
        f"TASK_URL={sh_single_quote(settings.base_url + '/api/agent/tasks/' + token)}",
        "json_escape() {",
        "  local s=\"${1-}\"",
        "  s=${s//\\\\/\\\\\\\\}",
        "  s=${s//\\\"/\\\\\\\"}",
        "  s=${s//$'\\r'/}",
        "  s=${s//$'\\n'/ }",
        "  printf '%s' \"$s\"",
        "}",
        "post_json() {",
        "  suffix=\"$1\"; payload=\"$2\";",
        "  if command -v curl >/dev/null 2>&1; then curl -m 10 -sS -X POST -H 'Content-Type: application/json' -d \"$payload\" \"$TASK_URL/$suffix\" >/tmp/eventlab-post.out 2>/tmp/eventlab-post.err;",
        "  elif command -v wget >/dev/null 2>&1; then wget -T 10 -q -O /tmp/eventlab-post.out --header='Content-Type: application/json' --post-data=\"$payload\" \"$TASK_URL/$suffix\" 2>/tmp/eventlab-post.err; fi",
        "}",
        "post_log() { lvl=\"$1\"; msg=$(json_escape \"$2\"); post_json logs \"{\\\"level\\\":\\\"$lvl\\\",\\\"message\\\":\\\"$msg\\\"}\"; }",
        "HOSTNAME_VALUE=$(hostname 2>/dev/null || echo unknown)",
        "OS_VALUE=$(uname -a 2>/dev/null || echo linux)",
        "post_json start \"{\\\"hostname\\\":\\\"$(json_escape \"$HOSTNAME_VALUE\")\\\",\\\"os_name\\\":\\\"$(json_escape \"$OS_VALUE\")\\\",\\\"agent_version\\\":\\\"linux-bundle-1.0\\\"}\"",
        r"RUN_ID=$(sed -n 's/.*\"run_id\"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' /tmp/eventlab-post.out | head -n1)",
        "[ -z \"$RUN_ID\" ] && RUN_ID=0",
        "HAD_ERRORS=0",
        "post_log info 'Linux bundle started'",
    ]
    for s in scenarios:
        runner = s["runner"]
        if runner != "bash":
            parts.append(f"post_log warning {sh_single_quote('Skipped unsupported runner ' + runner + ' for Linux')}")
            continue
        script = render_script(s["script_body"], task, s)
        encoded = b64_utf8(script)
        scenario_name = str(s["name"])
        parts.extend([
            f"post_log info {sh_single_quote('Scenario started: ' + scenario_name)}",
            f"SCRIPT_FILE=$(mktemp /tmp/eventlab-{int(s['id'])}-XXXXXX.sh)",
            f"printf '%s' {sh_single_quote(encoded)} | base64 -d > \"$SCRIPT_FILE\" 2>/dev/null || printf '%s' {sh_single_quote(encoded)} | base64 --decode > \"$SCRIPT_FILE\"",
            "chmod 700 \"$SCRIPT_FILE\"",
            "OUTPUT_FILE=$(mktemp /tmp/eventlab-output-XXXXXX.log)",
            "bash \"$SCRIPT_FILE\" > \"$OUTPUT_FILE\" 2>&1",
            "EXIT_CODE=$?",
            "while IFS= read -r line; do [ -n \"$line\" ] && post_log info \"$line\"; done < \"$OUTPUT_FILE\"",
            "if [ \"$EXIT_CODE\" -eq 0 ]; then post_log success 'Scenario completed'; else HAD_ERRORS=1; post_log error \"Scenario exit code $EXIT_CODE\"; fi",
            "rm -f \"$SCRIPT_FILE\" \"$OUTPUT_FILE\"",
        ])
    parts.extend([
        "if [ \"$HAD_ERRORS\" -eq 0 ]; then FINAL_STATUS=completed; else FINAL_STATUS=failed; fi",
        "post_json finish \"{\\\"run_id\\\":$RUN_ID,\\\"status\\\":\\\"$FINAL_STATUS\\\"}\"",
        "echo \"Diploma EventLab finished with status=$FINAL_STATUS\"",
    ])
    return "\n".join(parts) + "\n"

def register_routes(app: FastAPI) -> None:
    @app.exception_handler(401)
    async def auth_error(request: Request, exc: HTTPException):
        flash(request, "Нужно войти в систему", "warning")
        return redirect("/login")

    @app.exception_handler(403)
    async def forbidden(request: Request, exc: HTTPException):
        flash(request, "Недостаточно прав для действия", "danger")
        return redirect("/dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        if current_user(request):
            return redirect("/dashboard")
        return redirect("/login")

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return render(request, "login.html")

    @app.post("/login")
    async def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        csrf_form: Annotated[str, Form(alias="_csrf")],
    ):
        assert_csrf(request, csrf_form)
        user = get_user_by_username(username)
        ip = request.client.host if request.client else ""
        if not user:
            audit(None, "login_failed", f"unknown user {username}", ip)
            flash(request, "Неверный логин или пароль", "danger")
            return redirect("/login")
        locked_until = parse_iso(user["locked_until"])
        if locked_until and locked_until > utcnow():
            flash(request, f"Учётная запись временно заблокирована до {locked_until.isoformat()}", "danger")
            return redirect("/login")
        if not int(user["is_active"]) or not verify_password(password, user["password_hash"]):
            failures = int(user["failed_login_count"] or 0) + 1
            lock = iso(utcnow() + timedelta(minutes=10)) if failures >= 5 else None
            update_login_failure(int(user["id"]), lock)
            audit(int(user["id"]), "login_failed", "bad password", ip)
            flash(request, "Неверный логин или пароль", "danger")
            return redirect("/login")
        request.session.clear()
        request.session["user_id"] = int(user["id"])
        request.session["csrf"] = csrf_token()
        update_login_success(int(user["id"]))
        audit(int(user["id"]), "login_success", "", ip)
        return redirect("/dashboard")

    @app.post("/logout")
    async def logout(request: Request, csrf_form: Annotated[str, Form(alias="_csrf")]):
        assert_csrf(request, csrf_form)
        user = current_user(request)
        if user:
            audit(int(user["id"]), "logout", "", request.client.host if request.client else "")
        request.session.clear()
        return redirect("/login")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request, user=Depends(require_login)):
        return render(
            request,
            "dashboard.html",
            {
                "tasks": list_tasks(20),
                "scenarios": list_scenarios(active_only=True),
                "audit_logs": list_audit(10) if user["role"] == "admin" else [],
            },
        )

    @app.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request, user=Depends(require_role("admin"))):
        return render(request, "users.html", {"users": list_users()})

    @app.post("/users")
    async def users_create(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        role: Annotated[str, Form()],
        csrf_form: Annotated[str, Form(alias="_csrf")],
        user=Depends(require_role("admin")),
    ):
        assert_csrf(request, csrf_form)
        if len(password) < 10:
            flash(request, "Пароль должен быть не короче 10 символов", "danger")
            return redirect("/users")
        try:
            create_user(username, password, role)
            audit(int(user["id"]), "user_created", username, request.client.host if request.client else "")
            flash(request, "Пользователь создан", "success")
        except Exception as exc:
            flash(request, f"Не удалось создать пользователя: {safe_text(exc)}", "danger")
        return redirect("/users")

    @app.get("/scenarios", response_class=HTMLResponse)
    async def scenarios_page(request: Request, user=Depends(require_login)):
        return render(request, "scenarios.html", {"scenarios": list_scenarios()})

    @app.get("/scenarios/new", response_class=HTMLResponse)
    async def scenarios_new_page(request: Request, user=Depends(require_role("admin", "operator"))):
        return render(request, "scenario_form.html", {"scenario": None})

    @app.post("/scenarios/new")
    async def scenarios_new(
        request: Request,
        name: Annotated[str, Form()],
        description: Annotated[str, Form()],
        target_type: Annotated[str, Form()],
        runner: Annotated[str, Form()],
        script_body: Annotated[str, Form()],
        csrf_form: Annotated[str, Form(alias="_csrf")],
        user=Depends(require_role("admin", "operator")),
    ):
        assert_csrf(request, csrf_form)
        try:
            sid = create_scenario(name, description, target_type, runner, script_body, int(user["id"]))
            audit(int(user["id"]), "scenario_created", f"scenario_id={sid}", request.client.host if request.client else "")
            flash(request, "Сценарий добавлен", "success")
            return redirect("/scenarios")
        except Exception as exc:
            flash(request, f"Ошибка: {safe_text(exc)}", "danger")
            return redirect("/scenarios/new")

    @app.get("/scenarios/{scenario_id}/edit", response_class=HTMLResponse)
    async def scenarios_edit_page(request: Request, scenario_id: int, user=Depends(require_role("admin", "operator"))):
        scenario = get_scenario(scenario_id)
        if not scenario:
            raise HTTPException(status_code=404)
        return render(request, "scenario_form.html", {"scenario": scenario})

    @app.post("/scenarios/{scenario_id}/edit")
    async def scenarios_edit(
        request: Request,
        scenario_id: int,
        name: Annotated[str, Form()],
        description: Annotated[str, Form()],
        target_type: Annotated[str, Form()],
        runner: Annotated[str, Form()],
        script_body: Annotated[str, Form()],
        is_active: Annotated[str | None, Form()] = None,
        csrf_form: Annotated[str, Form(alias="_csrf")] = "",
        user=Depends(require_role("admin", "operator")),
    ):
        assert_csrf(request, csrf_form)
        update_scenario(scenario_id, name, description, target_type, runner, script_body, is_active == "on")
        audit(int(user["id"]), "scenario_updated", f"scenario_id={scenario_id}", request.client.host if request.client else "")
        flash(request, "Сценарий обновлён", "success")
        return redirect("/scenarios")

    @app.get("/tasks/new", response_class=HTMLResponse)
    async def task_new_page(request: Request, target_type: str = "windows", user=Depends(require_role("admin", "operator"))):
        if target_type not in {"windows", "linux", "ids"}:
            target_type = "windows"
        return render(request, "task_new.html", {"scenarios": list_scenarios(target_type, True), "target_type": target_type})

    @app.post("/tasks/new")
    async def task_new(
        request: Request,
        title: Annotated[str, Form()],
        target_type: Annotated[str, Form()],
        event_count: Annotated[int, Form()],
        delay_ms: Annotated[int, Form()],
        target_host: Annotated[str, Form()] = "",
        target_port: Annotated[int, Form()] = 0,
        scenario_ids: Annotated[list[int], Form()] = [],
        csrf_form: Annotated[str, Form(alias="_csrf")] = "",
        user=Depends(require_role("admin", "operator")),
    ):
        assert_csrf(request, csrf_form)
        if not scenario_ids:
            flash(request, "Выберите хотя бы один сценарий", "danger")
            return redirect(f"/tasks/new?target_type={target_type}")
        target_host_clean = validate_host(target_host)
        token = generate_token()
        token_preview = token[:8] + "..." + token[-6:]
        try:
            task_id = create_task(
                title=title,
                target_type=target_type,
                event_count=event_count,
                delay_ms=delay_ms,
                target_host=target_host_clean,
                target_port=target_port,
                token=token,
                token_preview=token_preview,
                expires_at=token_expiry(settings.token_ttl_hours),
                created_by=int(user["id"]),
                scenario_ids=scenario_ids,
            )
            request.session[f"task_token_{task_id}"] = token
            audit(int(user["id"]), "task_created", f"task_id={task_id}", request.client.host if request.client else "")
            flash(request, "Задание создано. Ссылка показана на этой странице и хранится только в текущей сессии.", "success")
            return redirect(f"/tasks/{task_id}")
        except Exception as exc:
            flash(request, f"Ошибка создания задания: {safe_text(exc)}", "danger")
            return redirect(f"/tasks/new?target_type={target_type}")

    @app.get("/tasks/{task_id}", response_class=HTMLResponse)
    async def task_detail(request: Request, task_id: int, user=Depends(require_login)):
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404)
        token = task_token_from_session(request, task_id)
        agent_url = f"{settings.base_url}/api/agent/tasks/{token}" if token else None
        return render(
            request,
            "task_detail.html",
            {
                "task": task,
                "scenarios": task_scenarios(task_id),
                "logs": task_logs(task_id),
                "runs": list_agent_runs(task_id),
                "agent_url": agent_url,
            },
        )

    @app.get("/tasks/{task_id}/report", response_class=HTMLResponse)
    async def task_report(request: Request, task_id: int, user=Depends(require_login)):
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404)
        return render(
            request,
            "report.html",
            {"task": task, "scenarios": task_scenarios(task_id), "logs": task_logs(task_id, 2000), "runs": list_agent_runs(task_id)},
        )

    @app.get("/download/agents/windows", response_class=FileResponse)
    async def download_windows_agent(user=Depends(require_login)):
        return FileResponse(str(PROJECT_DIR / "agents" / "windows_agent.ps1"), filename="windows_agent.ps1")

    @app.get("/download/agents/linux", response_class=FileResponse)
    async def download_linux_agent(user=Depends(require_login)):
        return FileResponse(str(PROJECT_DIR / "agents" / "linux_agent.sh"), filename="linux_agent.sh")

    @app.get("/download/agents/python", response_class=FileResponse)
    async def download_python_agent(user=Depends(require_login)):
        return FileResponse(str(PROJECT_DIR / "agents" / "python_agent.py"), filename="python_agent.py")

    @app.get("/api/agent/tasks/{token}")
    async def agent_get_task(token: str):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        expires = parse_iso(task["expires_at"])
        if expires and expires < utcnow():
            set_task_status(int(task["id"]), "expired")
            raise HTTPException(status_code=410, detail="task expired")
        scenarios = []
        for s in task_scenarios(int(task["id"])):
            if not int(s["is_active"]):
                continue
            scenarios.append(
                {
                    "id": int(s["id"]),
                    "name": s["name"],
                    "target_type": s["target_type"],
                    "runner": s["runner"],
                    "script_body": render_script(s["script_body"], task, s),
                }
            )
        return {
            "task": {
                "id": int(task["id"]),
                "title": task["title"],
                "target_type": task["target_type"],
                "event_count": int(task["event_count"]),
                "delay_ms": int(task["delay_ms"]),
                "target_host": task["target_host"],
                "target_port": int(task["target_port"] or 0),
                "status": task["status"],
            },
            "scenarios": scenarios,
        }

    @app.get("/api/agent/tasks/{token}/bundle/windows.ps1", response_class=PlainTextResponse)
    async def agent_windows_bundle(token: str):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        expires = parse_iso(task["expires_at"])
        if expires and expires < utcnow():
            set_task_status(int(task["id"]), "expired")
            raise HTTPException(status_code=410, detail="task expired")
        return PlainTextResponse(build_windows_bundle_for_token(token, task, task_scenarios(int(task["id"]))), media_type="text/plain; charset=utf-8")

    @app.get("/api/agent/tasks/{token}/bundle/linux.sh", response_class=PlainTextResponse)
    async def agent_linux_bundle(token: str):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        expires = parse_iso(task["expires_at"])
        if expires and expires < utcnow():
            set_task_status(int(task["id"]), "expired")
            raise HTTPException(status_code=410, detail="task expired")
        return PlainTextResponse(build_linux_bundle_for_token(token, task, task_scenarios(int(task["id"]))), media_type="text/plain; charset=utf-8")

    @app.post("/api/agent/tasks/{token}/start")
    async def agent_start(token: str, request: Request):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        body = await read_agent_json(request)
        run_id = create_agent_run(
            int(task["id"]),
            str(body.get("hostname", "")),
            str(body.get("os_name", "")),
            str(body.get("agent_version", "")),
        )
        set_task_status(int(task["id"]), "running")
        msg = f"Agent started: host={body.get('hostname','')}, os={body.get('os_name','')}, run_id={run_id}"
        add_task_log(int(task["id"]), "info", msg)
        await manager.broadcast(int(task["id"]), {"type": "log", "level": "info", "message": msg})
        return {"run_id": run_id}

    @app.post("/api/agent/tasks/{token}/logs")
    async def agent_log(token: str, request: Request):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        body = await read_agent_json(request)
        level = str(body.get("level", "info"))
        message = str(body.get("message", ""))
        add_task_log(int(task["id"]), level, message)
        await manager.broadcast(int(task["id"]), {"type": "log", "level": level, "message": message})
        return {"ok": True}

    @app.post("/api/agent/tasks/{token}/finish")
    async def agent_finish(token: str, request: Request):
        task = get_task_by_token(token)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        body = await read_agent_json(request)
        status = str(body.get("status", "completed"))
        if status not in {"completed", "failed"}:
            status = "failed"
        run_id = int(body.get("run_id") or 0)
        if run_id:
            finish_agent_run(run_id, status)
        set_task_status(int(task["id"]), status)
        msg = f"Agent finished with status={status}"
        add_task_log(int(task["id"]), "success" if status == "completed" else "error", msg)
        await manager.broadcast(int(task["id"]), {"type": "finish", "level": status, "message": msg})
        return {"ok": True}

    @app.websocket("/ws/tasks/{task_id}")
    async def task_ws(websocket: WebSocket, task_id: int):
        user_id = websocket.session.get("user_id") if hasattr(websocket, "session") else None
        if not user_id:
            await websocket.close(code=1008)
            return
        await manager.connect(task_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(task_id, websocket)


app = create_app()
