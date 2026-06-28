"""Тесты Web-GUI сервера.

Запускаются только если установлен fastapi (опциональная зависимость
[gui]). В CI без [gui] — пропускаются.
"""
import io
import json
import zipfile

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


def test_picked_folder_converts_in_place(
    client, tmp_path, monkeypatch
):
    """②: папка из родного диалога → .md рядом с исходниками."""
    (tmp_path / "alpha.csv").write_text(
        "m,v\nA,1\n", encoding="utf-8"
    )
    (tmp_path / "beta.html").write_text(
        "<p>B</p>", encoding="utf-8"
    )
    monkeypatch.setattr(gui_server, "_has_tkinter", lambda: True)
    monkeypatch.setattr(
        gui_server, "_native_pick", lambda kind: [str(tmp_path)]
    )
    r = client.post(
        "/api/convert/picked", data={"kind": "folder"}
    )
    assert r.status_code == 200
    made = sorted(p.name for p in tmp_path.glob("*.md"))
    assert made == ["alpha.md", "beta.md"]
    assert '"output"' in r.text


def test_picked_cancelled(client, monkeypatch):
    """②: отмена диалога → событие cancelled, без падений."""
    monkeypatch.setattr(gui_server, "_has_tkinter", lambda: True)
    monkeypatch.setattr(
        gui_server, "_native_pick", lambda kind: []
    )
    r = client.post(
        "/api/convert/picked", data={"kind": "files"}
    )
    assert r.status_code == 200
    assert "cancelled" in r.text


def test_url_endpoint_reads_form_not_query(client):
    """URL и флаги читаются из тела (Form), а не из query → не 422.

    Приватный адрес отвергается SSRF-контролем, но это SSE-error
    (200), а не 422 — значит Form-параметр url принят из тела.
    """
    r = client.post(
        "/api/convert/url", data={"url": "http://127.0.0.1:9/x"}
    )
    assert r.status_code == 200
    assert '"event"' in r.text


def _zip_id(body):
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: ") and '"zip"' in line:
            return json.loads(line[6:]).get("zip_id")
    return None


def test_zip_folder_preserves_tree_and_dedups(client):
    """③: папка из браузера → zip, структура и dedup сохранены."""
    files = [
        ("files", ("report.csv",
                   io.BytesIO(b"m,v\nA,1\n"), "text/csv")),
        ("files", ("report.html",
                   io.BytesIO(b"<p>B</p>"), "text/html")),
        ("files", ("data.json",
                   io.BytesIO(b'{"k":"C"}'), "application/json")),
    ]
    paths = [
        "proj/a/report.csv",
        "proj/a/report.html",
        "proj/b/data.json",
    ]
    r = client.post(
        "/api/convert/zip", files=files,
        data={"paths": json.dumps(paths)},
    )
    assert r.status_code == 200
    zid = _zip_id(r.text)
    assert zid
    zr = client.get("/api/download_zip", params={"zip_id": zid})
    assert zr.status_code == 200
    assert zr.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(zr.content))
    assert sorted(z.namelist()) == [
        "proj/a/report (2).md",
        "proj/a/report.md",
        "proj/b/data.md",
    ]


def test_zip_paths_traversal_sanitized(client):
    """③: '..'/абсолютные части в путях не дают выйти за дерево."""
    files = [
        ("files", ("x.csv",
                   io.BytesIO(b"a,b\n1,2\n"), "text/csv")),
    ]
    paths = ["../../evil/x.csv"]
    r = client.post(
        "/api/convert/zip", files=files,
        data={"paths": json.dumps(paths)},
    )
    assert r.status_code == 200
    zid = _zip_id(r.text)
    assert zid
    z = zipfile.ZipFile(io.BytesIO(
        client.get(
            "/api/download_zip", params={"zip_id": zid}
        ).content
    ))
    for n in z.namelist():
        assert ".." not in n
        assert not n.startswith("/")


def test_download_zip_not_found(client):
    """③: неизвестный zip_id → 404."""
    r = client.get(
        "/api/download_zip", params={"zip_id": "nope123"}
    )
    assert r.status_code == 404


def test_zip_upload_expands_to_md_zip(client):
    """Загрузка .zip: распаковка + конвертация каждого → .zip с .md."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("report.csv", "m,v\nA,1\n")
        z.writestr("sub/data.json", '{"k":"B"}')
    r = client.post(
        "/api/convert/files",
        files={"files": (
            "bundle.zip", io.BytesIO(buf.getvalue()),
            "application/zip",
        )},
    )
    assert r.status_code == 200
    zid = _zip_id(r.text)
    assert zid, "архив не дал zip_id"
    z = zipfile.ZipFile(io.BytesIO(
        client.get(
            "/api/download_zip", params={"zip_id": zid}
        ).content
    ))
    assert sorted(z.namelist()) == ["report.md", "sub/data.md"]


def test_insecure_ssl_flag_reaches_download(client, monkeypatch):
    """insecure_ssl=true → verify_ssl=False доходит до _download_url."""
    cap = {}

    def fake(url, timeout, max_bytes, allow_private,
             verify_ssl=True):
        cap["v"] = verify_ssl
        raise ValueError("stop")

    monkeypatch.setattr(gui_server.core, "_download_url", fake)
    r = client.post(
        "/api/convert/url",
        data={"url": "https://example.com/x",
              "insecure_ssl": "true"},
    )
    assert r.status_code == 200
    assert cap.get("v") is False


def test_ssl_verified_by_default(client, monkeypatch):
    """Без флага verify_ssl=True (строгая проверка по умолчанию)."""
    cap = {}

    def fake(url, timeout, max_bytes, allow_private,
             verify_ssl=True):
        cap["v"] = verify_ssl
        raise ValueError("stop")

    monkeypatch.setattr(gui_server.core, "_download_url", fake)
    client.post(
        "/api/convert/url", data={"url": "https://example.com/x"}
    )
    assert cap.get("v") is True
