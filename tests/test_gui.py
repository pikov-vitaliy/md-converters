"""Тесты Web-GUI сервера.

Запускаются только если установлен fastapi (опциональная зависимость
[gui]). В CI без [gui] — пропускаются.
"""
import io
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from fastapi.testclient import TestClient  # noqa: E402

import gui_server  # noqa: E402


@pytest.fixture
def client():
    """TestClient с localhost base_url (BLK-6+S1 middleware проходит)."""
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


def test_origin_check_rejects_cross_site():
    """S1: Origin с внешнего сайта → 403."""
    with TestClient(
        gui_server.app,
        base_url="http://127.0.0.1:8765",
    ) as c:
        r = c.get(
            "/",
            headers={
                "host": "127.0.0.1:8765",
                "origin": "https://evil.com",
            },
        )
        assert r.status_code == 403


def test_convert_csv_file(client):
    """Конвертация CSV через upload → SSE с done."""
    csv_data = b"a,b\n1,2\n"
    files = {
        "files": ("test.csv", io.BytesIO(csv_data), "text/csv"),
    }
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    body = r.text
    assert '"done"' in body
    assert "test.csv" in body
    assert "download_id" in body


def test_b1_form_params_actually_work(client):
    """B1: frontmatter=False передаётся через Form, не теряется."""
    csv_data = b"a,b\n1,2\n"
    files = {
        "files": ("b1test.csv", io.BytesIO(csv_data), "text/csv"),
    }
    data = {
        "frontmatter": "false",
        "force": "true",
    }
    r = client.post(
        "/api/convert/files", files=files, data=data
    )
    assert r.status_code == 200
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data: ") and "done" in line:
            payload = json.loads(line[6:])
            dl_id = payload.get("download_id", "")
            assert dl_id, "download_id пустой"
            r2 = client.get(
                "/api/download",
                params={"dl_id": dl_id},
            )
            assert r2.status_code == 200
            content = r2.text
            # CSV → GFM таблица
            assert "| a | b |" in content or "a,b" in content
            # front-matter не должен генерироваться
            assert not content.startswith("---"), (
                "front-matter не должен генерироваться"
            )
            break


def test_download_works_after_tmpdir_cleanup(client):
    """B2: файл доступен для скачивания после удаления tmpdir."""
    csv_data = b"x,y\n3,4\n"
    files = {
        "files": ("b2test.csv", io.BytesIO(csv_data), "text/csv"),
    }
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data: ") and "done" in line:
            payload = json.loads(line[6:])
            dl_id = payload.get("download_id", "")
            assert dl_id, "download_id пустой"
            r2 = client.get(
                "/api/download",
                params={"dl_id": dl_id},
            )
            assert r2.status_code == 200
            # CSV → GFM таблица
            assert "| x | y |" in r2.text or "x,y" in r2.text
            break


def test_h1_path_traversal_filename(client):
    """H1: имя файла с .. санитизируется до basename."""
    csv_data = b"h1test\n"
    files = {
        "files": (
            "..\\..\\evil.csv",
            io.BytesIO(csv_data),
            "text/csv",
        ),
    }
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    # Файл должен быть сохранён как evil.csv
    assert "evil.csv" in r.text
    # Имя файла в SSE не должно содержать ..
    for line in r.text.split("\n"):
        line = line.strip()
        if line.startswith("data: ") and "done" in line:
            payload = json.loads(line[6:])
            # file field — только basename, без пути
            assert ".." not in payload.get("file", "")
            break


def test_download_not_found(client):
    """GET /api/download с несуществующим dl_id → 404."""
    r = client.get(
        "/api/download",
        params={"dl_id": "nonexistent123"},
    )
    assert r.status_code == 404


def _done_events(body):
    return [
        json.loads(p[6:])
        for p in body.split("\n\n")
        if p.strip().startswith("data: ")
        and json.loads(p.strip()[6:]).get("event") == "done"
    ]


def test_same_stem_batch_no_cross_assignment(client):
    """HIGH#1: файлы с ОДИНАКОВЫМ stem в батче не путают контент.

    report.csv + report.html + report.json — у каждого свой маркер;
    превью и скачивание каждого должны отдавать ИМЕННО его контент,
    а не чужой (раньше угадывание по stem отдавало report.md всем).
    """
    files = [
        ("files", ("report.csv",
                   io.BytesIO(b"m,v\nCSVUNIQUE,1\n"), "text/csv")),
        ("files", ("report.html",
                   io.BytesIO(b"<p>HTMLUNIQUE</p>"), "text/html")),
        ("files", ("report.json",
                   io.BytesIO(b'{"k":"JSONUNIQUE"}'),
                   "application/json")),
    ]
    r = client.post("/api/convert/files", files=files)
    assert r.status_code == 200
    dones = _done_events(r.text)
    assert len(dones) == 3
    markers = {
        "csv": "CSVUNIQUE",
        "html": "HTMLUNIQUE",
        "json": "JSONUNIQUE",
    }
    for d in dones:
        ext = d["file"].rsplit(".", 1)[-1]
        want = markers[ext]
        dl_id = d.get("download_id", "")
        assert dl_id, f"нет download_id для {d['file']}"
        content = client.get(
            "/api/download", params={"dl_id": dl_id}
        ).text
        assert want in content, (
            f"{d['file']}: ожидался {want}, получен чужой контент"
        )
        # И превью того же файла — его собственное
        assert want in d.get("preview", "")
