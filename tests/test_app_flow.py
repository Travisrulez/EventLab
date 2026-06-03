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

from app.repository import add_task_log, get_user_by_username


def ensure_admin_user():
    if not get_user_by_username("admin"):
        create_user("admin", "StrongPassword123", "admin")


def test_admin_load_test_flow_and_delete_task():
    ensure_admin_user()
    login()

    r = client.get("/load-test?target_type=linux")
    assert r.status_code == 200
    assert "Нагрузочное тестирование" in r.text
    token = csrf_from(r.text)

    r = client.post(
        "/load-test",
        data={
            "_csrf": token,
            "title": "linux load smoke",
            "target_type": "linux",
            "event_count": "2",
            "delay_ms": "0",
            "target_host": "127.0.0.1",
            "target_port": "80",
            "scenario_ids": "5",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = client.get(r.headers["location"])
    assert detail.status_code == 200
    assert "load test" in detail.text

    m = re.search(r'value="(http://testserver/api/agent/tasks/[^"]+)"', detail.text)
    assert m, detail.text[:1000]
    task_url = m.group(1)

    bundle = client.get(task_url.replace("http://testserver", "") + "/bundle/linux.sh")
    assert bundle.status_code == 200
    assert "post_metrics 'task_start'" in bundle.text
    assert "METRIC stage=$stage" in bundle.text

    task_id = int(r.headers["location"].rsplit("/", 1)[-1])
    add_task_log(task_id, "metric", "METRIC stage=task_start loadavg=0.10,0.20,0.30 mem_available_mb=1000 mem_total_mb=2000 processes=77 tmp_free_mb=500")
    detail_with_metrics = client.get(r.headers["location"])
    assert detail_with_metrics.status_code == 200
    assert "Графики нагрузки" in detail_with_metrics.text
    metrics = client.get(f"/tasks/{task_id}/metrics.json")
    assert metrics.status_code == 200
    assert metrics.json()["points"][0]["mem_used_percent"] == 50.0

    csrf = csrf_from(detail.text)
    deleted = client.post(f"/tasks/{task_id}/delete", data={"_csrf": csrf}, follow_redirects=False)
    assert deleted.status_code == 303
    assert client.get(f"/tasks/{task_id}").status_code == 404
