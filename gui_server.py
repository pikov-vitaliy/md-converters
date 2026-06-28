"""Web-GUI сервер для md-converters.

Запуск: tomd-gui или python -m gui_server
Слушает 127.0.0.1:8765 — только локально, без внешнего доступа.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import socket
import sys
import tempfile
import time
import uuid
import webbrowser
from collections import OrderedDict
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

import convert_to_md as core

_STATIC = Path(__file__).parent / "gui_static"
_PORT_DEFAULT = 8765
_PORT_TRIES = 5
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_PREVIEW_CHARS = 5000
# Запретные корни для out_dir (защита от записи в системные папки)
_FORBIDDEN_OUT_DIRS = {
    Path("C:\\Windows"), Path("C:\\Program Files"),
    Path("C:\\Program Files (x86)"),
    Path("C:\\ProgramData"),
    Path("C:\\Windows\\System32"),
}


def _validate_out_dir(raw: str | None) -> Path | None:
    """Валидация папки вывода: не системная, не UNC, создава­емая."""
    if not raw or not raw.strip():
        return None
    p = Path(raw.strip())
    if str(p).startswith("\\\\"):
        raise ValueError("UNC-пути не разрешены для папки вывода")
    resolved = p.resolve()
    for forbidden in _FORBIDDEN_OUT_DIRS:
        try:
            if resolved == forbidden or forbidden in (
                resolved.parents
            ):
                msg = (
                    f"Папка вывода не может быть внутри"
                    f" {forbidden}"
                )
                raise ValueError(msg)
        except (OSError, ValueError):
            pass
    return p

_port: int = _PORT_DEFAULT
_last_heartbeat = time.time()

# LRU-хранилище для скачивания: {dl_id: (filename, content, timestamp)}
# Максимум 20 записей / 50 МБ суммарно, TTL 30 минут.
_MAX_DL_ENTRIES = 20
_MAX_DL_BYTES = 50 * 1024 * 1024
_DL_TTL = 30 * 60
_downloads: OrderedDict[
    str, tuple[str, str, float]
] = OrderedDict()


def _add_download(dl_id: str, filename: str, content: str):
    """Добавляет результат с LRU-очисткой по счётчику и размеру."""
    _downloads[dl_id] = (filename, content, time.time())
    _downloads.move_to_end(dl_id)
    while len(_downloads) > _MAX_DL_ENTRIES:
        _downloads.popitem(last=False)
    total = sum(len(v[1]) for v in _downloads.values())
    while total > _MAX_DL_BYTES and len(_downloads) > 1:
        _, _, _ = _downloads.popitem(last=False)
        total = sum(len(v[1]) for v in _downloads.values())


def _purge_expired_downloads():
    """Удаляет записи старше _DL_TTL."""
    now = time.time()
    expired = [
        k for k, v in _downloads.items()
        if now - v[2] > _DL_TTL
    ]
    for k in expired:
        _downloads.pop(k, None)


# --- Port finding (BLK-3) ---

def _find_free_port() -> int:
    """Перебор портов 8765, 8766, ... до свободного."""
    for offset in range(_PORT_TRIES):
        port = _PORT_DEFAULT + offset
        with socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        ) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    msg = (
        f"No free port in {_PORT_DEFAULT}–"
        f"{_PORT_DEFAULT + _PORT_TRIES - 1}"
    )
    raise RuntimeError(msg)


# --- Lifespan ---

# Глобальная ссылка на uvicorn-сервер для graceful shutdown
_uvicorn_server: uvicorn.Server | None = None

@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _port, _uvicorn_server
    asyncio.create_task(_open_browser_when_ready(_port))
    asyncio.create_task(_auto_shutdown_check())
    yield


app = FastAPI(lifespan=_lifespan)
app.mount(
    "/static", StaticFiles(directory=_STATIC), name="static"
)


# --- Browser open after port ready (BLK-2) ---

async def _open_browser_when_ready(port: int) -> None:
    """Ждём пока uvicorn начнёт слушать, потом открываем браузер."""
    for _ in range(20):
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", port
            )
            writer.close()
            await writer.wait_closed()
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return
        except (ConnectionError, OSError):
            await asyncio.sleep(0.5)


# --- DNS rebinding / CSRF protection (BLK-6, S1) ---

@app.middleware("http")
async def _check_origin(request: Request, call_next):
    """BLK-6+S1: отвергаем запросы не с localhost.

    Проверяем И Host, И Origin — браузер ставит Host
    автоматически, но Origin защищает от CSRF с
    соседнего сайта.
    """
    host = request.headers.get("host", "").split(":")[0]
    if host not in _ALLOWED_HOSTS:
        return JSONResponse(
            {"error": "forbidden"}, status_code=403
        )
    origin = request.headers.get("origin", "")
    if origin:
        origin_host = (
            origin.split("//")[-1].split("/")[0].split(":")[0]
        )
        if origin_host not in _ALLOWED_HOSTS:
            return JSONResponse(
                {"error": "forbidden"}, status_code=403
            )
    return await call_next(request)


# --- SSE helper ---

def _sse(event: str, data: dict) -> str:
    payload = json.dumps(
        {"event": event, **data}, ensure_ascii=False
    )
    return f"data: {payload}\n\n"


# --- Safe filename (H1) ---

def _safe_filename(name: str) -> str:
    """H1: только basename, без пути и .. — защита от traversal."""
    return Path(name).name or "unknown"


# --- Streaming upload (BLK-5) ---

async def _save_upload_streaming(
    upload: UploadFile, dest: Path
) -> int:
    """BLK-5: чанки по 1 МБ, без загрузки в RAM."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with dest.open("wb") as f:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                msg = (
                    f"File too large: {upload.filename} "
                    f"({_MAX_UPLOAD_BYTES // 1048576} MB max)"
                )
                raise ValueError(msg)
            f.write(chunk)
    return total


# --- stdout/stderr capture ---

def _convert_with_capture(
    path: Path, opts: dict
) -> dict:
    """Конвертация с перехватом stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
         contextlib.redirect_stderr(err):
        status = core.convert_file(path, opts)
    return {
        "status": status,
        "log": out.getvalue(),
        "warnings": err.getvalue(),
    }


def _convert_url_with_capture(
    url: str, opts: dict
) -> dict:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), \
         contextlib.redirect_stderr(err):
        status = core.convert_url(url, opts)
    return {
        "status": status,
        "log": out.getvalue(),
        "warnings": err.getvalue(),
    }


# --- Opts adapter (BLK-4: per-request) ---

def _gui_opts(
    force: bool = False,
    frontmatter: bool = True,
    keep_images: bool = False,
    pdf_tables: str = "auto",
    only_spec: str | None = None,
    out_dir: str | None = None,
) -> dict:
    """BLK-4: новый opts на каждый запрос."""
    only = None
    if only_spec:
        only = core._suffix_set(only_spec)
    parsed = {
        "force": force,
        "frontmatter": frontmatter,
        "keep_images": keep_images,
        "unsafe_raw_markdown": False,
        "allow_private_url": False,
        "url_timeout": core._DEFAULT_URL_TIMEOUT,
        "max_url_mb": core._DEFAULT_MAX_URL_MB,
        "max_input_mb": core._DEFAULT_MAX_INPUT_MB,
        "conversion_timeout": (
            core._DEFAULT_CONVERSION_TIMEOUT
        ),
        "sandbox": True,
        "out_dir": _validate_out_dir(out_dir),
        "mirror": False,
        "only": only,
        "pdf_tables": pdf_tables,
        "errors": [],
    }
    return core._build_opts(parsed, default_only=None)


# --- Find output .md ---

def _find_output(
    src: Path, opts: dict,
    before: set[Path] | None = None,
) -> Path | None:
    """Находит НОВЫЙ .md, созданный конвертацией.

    Снимок до/после: если before передан — возвращает .md, которого
    не было в before. Это единственный надёжный способ при одинаковых
    stem в батче (report.pdf + report.docx → report (2).md).
    Без before — fallback на glob по stem.
    """
    dest_dir = opts.get("out_dir") or src.parent
    if before is not None:
        after = set(dest_dir.glob("*.md"))
        new_files = after - before
        if len(new_files) == 1:
            return new_files.pop()
        if len(new_files) > 1:
            # Несколько новых — берём свежий по mtime
            return sorted(
                new_files,
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[0]
        return None
    # Fallback: glob по stem
    candidate = dest_dir / (src.stem + ".md")
    if candidate.exists():
        return candidate
    return None


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def index():
    """Главная страница."""
    index_path = _STATIC / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            "<h1>gui_static/index.html not found</h1>", 500
        )
    return HTMLResponse(
        index_path.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": (
                "no-cache, no-store, must-revalidate"
            ),
        },
    )


@app.get("/api/flags")
async def get_flags():
    """Значения флагов по умолчанию."""
    return {
        "force": False,
        "frontmatter": True,
        "keep_images": False,
        "pdf_tables": "auto",
        "only": None,
        "version": core.__version__,
        "supported_formats": sorted(
            core.SUPPORTED_SUFFIXES
        ),
        "max_upload_mb": _MAX_UPLOAD_BYTES // (1024 * 1024),
    }


_CONVERT_SEMAPHORE = asyncio.Semaphore(3)


# B1: Form(...) — параметры читаются из multipart body
@app.post("/api/convert/files")
async def convert_files(
    files: list[UploadFile],
    force: bool = Form(False),
    frontmatter: bool = Form(True),
    keep_images: bool = Form(False),
    pdf_tables: str = Form("auto"),
    only: str | None = Form(None),
    out_dir: str | None = Form(None),
) -> StreamingResponse:
    """Конвертация файлов с SSE-прогрессом (BLK-1: threadpool)."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )

    async def _convert_one(
        src: Path, name: str,
        before: set[Path],
    ) -> dict:
        """Конвертация одного файла с семафором (до 3 параллельно)."""
        async with _CONVERT_SEMAPHORE:
            try:
                result = await asyncio.to_thread(
                    _convert_with_capture, src, opts
                )
            except Exception as exc:
                return {
                    "file": name,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                }
            md_path = _find_output(src, opts, before)
            preview = ""
            full_content = ""
            if md_path and md_path.exists():
                full_content = md_path.read_text(
                    encoding="utf-8"
                )
                preview = full_content[:_PREVIEW_CHARS]
            dl_id = ""
            if full_content:
                dl_id = uuid.uuid4().hex[:12]
                _add_download(
                    dl_id, src.stem + ".md", full_content
                )
            return {
                "file": name,
                "status": result["status"],
                "log": result["log"],
                "warnings": result["warnings"],
                "preview": preview,
                "download_id": dl_id,
            }

    async def generate() -> AsyncGenerator[str, None]:
        tmpdir = Path(tempfile.mkdtemp(prefix="md_gui_"))
        try:
            # 1. Загрузка всех файлов (последовательно — upload stream)
            jobs = []
            for upload in files:
                name = _safe_filename(
                    upload.filename or "unknown"
                )
                src = tmpdir / name
                try:
                    await _save_upload_streaming(
                        upload, src
                    )
                except (ValueError, OSError) as exc:
                    yield _sse("error", {
                        "file": name,
                        "error": str(exc),
                    })
                    continue
                yield _sse("start", {"file": name})
                jobs.append((src, name))

            # 2. Параллельная конвертация (до 3 одновременно)
            if jobs:
                # Снимок dest_dir ДО конвертации — чтобы найти
                # именно новые файлы (защита от same-stem)
                dest_dir = opts.get("out_dir") or tmpdir
                before = set(dest_dir.glob("*.md"))
                tasks = [
                    _convert_one(src, name, before)
                    for src, name in jobs
                ]
                results = await asyncio.gather(
                    *tasks, return_exceptions=False
                )
                # 3. Отдаём результаты последовательно
                for r in results:
                    if "error" in r:
                        yield _sse("error", r)
                    else:
                        yield _sse("done", r)

            yield _sse("complete", {})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/convert/url")
async def convert_url_endpoint(
    url: str = Form(...),
    force: bool = Form(False),
    frontmatter: bool = Form(True),
    keep_images: bool = Form(False),
    pdf_tables: str = Form("auto"),
    only: str | None = Form(None),
    out_dir: str | None = Form(None),
) -> StreamingResponse:
    """Конвертация URL с SSE-прогрессом."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield _sse("start", {"file": url})
        dest_dir = opts.get("out_dir") or Path.cwd()
        before = set(dest_dir.glob("*.md"))
        try:
            result = await asyncio.to_thread(
                _convert_url_with_capture, url, opts
            )
        except Exception as exc:
            yield _sse("error", {
                "file": url,
                "error": f"{type(exc).__name__}: {exc}",
            })
            yield _sse("complete", {})
            return

        # Находим НОВЫЙ .md через снимок до/после
        stem = core._url_stem(url)
        md_path = _find_output(
            Path(f"{stem}.csv"), opts, before
        )
        preview = ""
        full_content = ""
        if md_path and md_path.exists():
            full_content = md_path.read_text(
                encoding="utf-8"
            )
            preview = full_content[:_PREVIEW_CHARS]

        dl_id = ""
        if full_content:
            dl_id = uuid.uuid4().hex[:12]
            _add_download(
                dl_id, f"{stem}.md", full_content
            )

        yield _sse("done", {
            "file": url,
            "status": result["status"],
            "log": result["log"],
            "warnings": result["warnings"],
            "preview": preview,
            "download_id": dl_id,
        })
        yield _sse("complete", {})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/heartbeat")
async def heartbeat():
    """Heartbeat от вкладки — сервер жив, пока вкладка открыта."""
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"ok": True}


@app.get("/api/download")
async def download_file(dl_id: str):
    """Скачивание готового .md из памяти."""
    _purge_expired_downloads()
    entry = _downloads.get(dl_id)
    if not entry:
        return JSONResponse(
            {"error": "File not found"}, status_code=404
        )
    filename, content, _ts = entry
    encoded = quote(filename, safe="")
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{encoded}\"; "
                f"filename*=UTF-8''{encoded}"
            )
        },
    )


# --- Auto-shutdown ---

async def _auto_shutdown_check():
    """Авто-выключение: если вкладка закрыта 60с → graceful stop.

    Порог 60с (не 15): Chrome троттлит JS в фоновых вкладках
    до ~1/мин. 15с приводило к ложному убийству сервера.
    """
    while True:
        await asyncio.sleep(10)
        if time.time() - _last_heartbeat > 60:
            if _uvicorn_server is not None:
                _uvicorn_server.should_exit = True
            else:
                # Fallback для TestClient (без uvicorn server)
                import os
                import signal
                os.kill(
                    os.getpid(), signal.SIGINT
                )
            return


# --- Entrypoint ---

def main():
    """Точка входа tomd-gui: старт сервера."""
    global _port, _uvicorn_server
    _port = _find_free_port()
    if sys.stdout.encoding and \
       sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"MD Converter GUI: http://127.0.0.1:{_port}/")
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=_port,
        log_level="warning",
        server_header=False,
    )
    _uvicorn_server = uvicorn.Server(config)
    _uvicorn_server.run()


if __name__ == "__main__":
    main()
