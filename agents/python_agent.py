#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

AGENT_VERSION = "python-agent-1.0"


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body else {}


def post_json(task_url: str, suffix: str, payload: dict) -> dict:
    try:
        return request_json(task_url.rstrip("/") + "/" + suffix, "POST", payload)
    except Exception as exc:
        print(f"[agent-log-failed] {exc}", file=sys.stderr)
        return {}


def log(task_url: str, level: str, message: str) -> None:
    print(f"[{level}] {message}")
    post_json(task_url, "logs", {"level": level, "message": message})


def stream_reader(pipe, task_url: str, level: str) -> None:
    for raw in iter(pipe.readline, ""):
        line = raw.rstrip("\r\n")
        if line:
            log(task_url, level, line)
    pipe.close()


def run_script(task_url: str, runner: str, script_body: str, scenario_name: str) -> int:
    if runner not in {"powershell", "cmd", "bash"}:
        log(task_url, "warning", f"Unsupported runner: {runner}")
        return 0

    is_windows = platform.system().lower().startswith("win")
    if runner in {"powershell", "cmd"} and not is_windows:
        log(task_url, "warning", f"Skipped Windows runner on non-Windows host: {runner}")
        return 0
    if runner == "bash" and is_windows:
        log(task_url, "warning", "Skipped bash runner on Windows host")
        return 0

    suffix = ".ps1" if runner == "powershell" else ".cmd" if runner == "cmd" else ".sh"
    fd, path = tempfile.mkstemp(prefix="eventlab-", suffix=suffix)
    os.close(fd)
    script_path = Path(path)
    script_path.write_text(script_body, encoding="utf-8")
    if runner == "bash":
        script_path.chmod(0o700)
        cmd = ["bash", str(script_path)]
    elif runner == "powershell":
        cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "RemoteSigned", "-File", str(script_path)]
    else:
        cmd = ["cmd.exe", "/c", str(script_path)]

    log(task_url, "info", f"Scenario started: {scenario_name}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        threads = [
            threading.Thread(target=stream_reader, args=(proc.stdout, task_url, "info"), daemon=True),
            threading.Thread(target=stream_reader, args=(proc.stderr, task_url, "error"), daemon=True),
        ]
        for t in threads:
            t.start()
        code = proc.wait()
        for t in threads:
            t.join(timeout=2)
        if code == 0:
            log(task_url, "success", "Scenario completed")
        else:
            log(task_url, "error", f"Scenario exit code {code}")
        return code
    finally:
        try:
            script_path.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Diploma EventLab Python Agent")
    parser.add_argument("--task-url", required=True)
    args = parser.parse_args()
    task_url = args.task_url.rstrip("/")
    task = request_json(task_url)
    run = post_json(task_url, "start", {
        "hostname": socket.gethostname(),
        "os_name": platform.platform(),
        "agent_version": AGENT_VERSION,
    })
    run_id = int(run.get("run_id") or 0)
    had_errors = False
    for scenario in task.get("scenarios", []):
        code = run_script(task_url, scenario["runner"], scenario["script_body"], scenario.get("name", "scenario"))
        if code != 0:
            had_errors = True
    status = "failed" if had_errors else "completed"
    post_json(task_url, "finish", {"run_id": run_id, "status": status})
    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
