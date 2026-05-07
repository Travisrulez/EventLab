import os
import re
from pathlib import Path

os.environ["EVENTLAB_DB_PATH"] = "/tmp/eventlab-test.db"
os.environ["EVENTLAB_SECRET_KEY"] = "test-secret-key"
os.environ["EVENTLAB_BASE_URL"] = "http://testserver"

try:
    Path(os.environ["EVENTLAB_DB_PATH"]).unlink()
except FileNotFoundError:
    pass

from fastapi.testclient import TestClient

from app.main import app
from app.repository import create_user

client = TestClient(app)


def csrf_from(html: str) -> str:
    m = re.search(r'name="_csrf" value="([^"]+)"', html)
    assert m, html[:500]
    return m.group(1)


def login():
    r = client.get("/login")
    token = csrf_from(r.text)
    r = client.post("/login", data={"username": "admin", "password": "StrongPassword123", "_csrf": token}, follow_redirects=False)
    assert r.status_code == 303


def test_full_create_task_and_agent_bundle_flow():
    create_user("admin", "StrongPassword123", "admin")
    login()

    r = client.get("/tasks/new?target_type=linux")
    assert r.status_code == 200
    token = csrf_from(r.text)
    assert "Linux: syslog" in r.text

    r = client.post(
        "/tasks/new",
        data={
            "_csrf": token,
            "title": "test linux task",
            "target_type": "linux",
            "event_count": "1",
            "delay_ms": "0",
            "target_host": "example.com",
            "target_port": "80",
            "scenario_ids": "5",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = client.get(r.headers["location"])
    assert detail.status_code == 200
    m = re.search(r'value="(http://testserver/api/agent/tasks/[^"]+)"', detail.text)
    assert m, detail.text[:1000]
    task_url = m.group(1)

    payload = client.get(task_url.replace("http://testserver", ""))
    assert payload.status_code == 200
    assert payload.json()["task"]["title"] == "test linux task"

    bundle_url = task_url.replace("http://testserver", "") + "/bundle/linux.sh"
    bundle = client.get(bundle_url)
    assert bundle.status_code == 200
    assert "Linux bundle started" in bundle.text
    assert "base64" in bundle.text
