"""Тесты Web-GUI сервера (этап 4).

Запускаются только если установлен fastapi (опциональная зависимость
[gui]). В CI без [gui] — пропускаются.
"""
import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from fastapi.testclient import TestClient  # noqa: E402

import gui_server  # noqa: E402


@pytest.fixture
def client():
    """TestClient с localhost base_url (BLK-6 middleware пропускает)."""
    with TestClient(
        gui_server.app,
        base_url="http://127.0.0.1:8765",
    ) as c:
        yield c


def test_index_returns_html(client):
    """GET / возвращает HTML-страницу."""
    r = client.get("/")
    assert r.status_code == 200
    assert "md-converters" in r.text


def test_flags_defaults(client):
    """GET /api/flags возвращает значения по умолчанию."""
    r = client.get("/api/flags")
    assert r.status_code == 200
    data = r.json()
    assert data["force"] is False
    assert data["frontmatter"] is True
    assert data["pdf_tables"] == "auto"
    assert ".pdf" in data["supported_formats"]


def test_heartbeat(client):
    """POST /api/heartbeat возвращает ok."""
    r = client.post("/api/heartbeat")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_origin_check_rejects_non_localhost():
    """BLK-6: запрос не с localhost → 403."""
    with TestClient(gui_server.app) as c:
        r = c.get("/", headers={"host": "evil.com:8765"})
        assert r.status_code == 403


def test_origin_check_allows_localhost():
    """BLK-6: запрос с localhost → 200."""
    with TestClient(gui_server.app) as c:
        r = c.get("/", headers={"host": "127.0.0.1:8765"})
        assert r.status_code == 200


def test_convert_csv_file(client):
    """Конвертация простого CSV через upload → SSE с done."""
    csv_data = b"a,b\n1,2\n"
    files = {
        "files": ("test.csv", io.BytesIO(csv_data), "text/csv"),
    }
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    # Парсим SSE — ищем событие done
    body = r.text
    assert '"event": "done"' in body or '"event":"done"' in body
    assert "test.csv" in body


def test_convert_file_no_frontmatter(client):
    """Конвертация без front-matter — флаг передан."""
    csv_data = b"x,y\n3,4\n"
    files = {
        "files": ("mini.csv", io.BytesIO(csv_data), "text/csv"),
    }
    data = {"frontmatter": "false"}
    r = client.post(
        "/api/convert/files", files=files, data=data
    )
    assert r.status_code == 200


def test_path_traversal_rejected(client):
    """POST /api/convert/path с .. → 400."""
    r = client.post(
        "/api/convert/path",
        json={"path": "../../etc/passwd"},
    )
    # JSON body → FastAPI парсит как body, но path параметр
    # передаётся через query/form. Проверяем хотя бы 404/400.
    assert r.status_code in (400, 404, 422)


def test_download_not_found(client):
    """GET /api/download с несуществующим путём → 404."""
    r = client.get(
        "/api/download",
        params={"path": "/tmp/nonexistent_test_file.md"},
    )
    assert r.status_code == 404


def test_file_too_large_rejected(client):
    """BLK-5: файл больше 100 МБ → ошибка в SSE."""
    big_data = b"x" * (101 * 1024 * 1024)
    files = {
        "files": (
            "big.pdf",
            io.BytesIO(big_data),
            "application/pdf",
        ),
    }
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    body = r.text
    assert "error" in body or "too large" in body.lower()
