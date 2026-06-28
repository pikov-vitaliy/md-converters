"""Web-GUI сервер для md-converters.

Запуск: tomd-gui или python -m gui_server
Слушает 127.0.0.1:8765 — только локально, без внешнего доступа.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import shutil
import signal
import socket
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, UploadFile
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
_MAX_JOBS = 20
_JOB_TTL = 30 * 60
_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
_PREVIEW_CHARS = 5000

_port: int = _PORT_DEFAULT
_last_heartbeat = time.time()


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

@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _port
    asyncio.create_task(_open_browser_when_ready(_port))
    asyncio.create_task(_cleanup_loop())
    asyncio.create_task(_auto_shutdown_check())
    yield


app = FastAPI(lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


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


# --- DNS rebinding protection (BLK-6) ---

@app.middleware("http")
async def _check_origin(request: Request, call_next):
    """BLK-6: отвергаем запросы не с localhost."""
    host = request.headers.get("host", "").split(":")[0]
    if host not in _ALLOWED_HOSTS:
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


# --- Streaming upload (BLK-5) ---

async def _save_upload_streaming(
    upload: UploadFile, dest: Path
) -> int:
    """BLK-5: чанки по 1 МБ, без загрузки в RAM."""
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

def _convert_with_capture(path: Path, opts: dict) -> dict:
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


# --- URL convert with capture ---

def _convert_url_with_capture(url: str, opts: dict) -> dict:
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
        "out_dir": Path(out_dir) if out_dir else None,
        "mirror": False,
        "only": only,
        "pdf_tables": pdf_tables,
        "errors": [],
    }
    return core._build_opts(parsed, default_only=None)


# --- Find output .md ---

def _find_output(src: Path, opts: dict) -> Path | None:
    """Находит .md рядом с исходником (или в out_dir)."""
    dest_dir = opts.get("out_dir") or src.parent
    candidate = dest_dir / (src.stem + ".md")
    if candidate.exists():
        return candidate
    # Имя могло получить суффикс (2) при коллизии
    n = 2
    while True:
        c = dest_dir / f"{src.stem} ({n}).md"
        if c.exists():
            return c
        if not c.with_suffix("").exists():
            break
        n += 1
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
        index_path.read_text(encoding="utf-8")
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
        "supported_formats": sorted(core.SUPPORTED_SUFFIXES),
        "max_upload_mb": _MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.post("/api/convert/files")
async def convert_files(
    files: list[UploadFile],
    force: bool = False,
    frontmatter: bool = True,
    keep_images: bool = False,
    pdf_tables: str = "auto",
    only: str | None = None,
    out_dir: str | None = None,
) -> StreamingResponse:
    """Конвертация файлов с SSE-прогрессом (BLK-1: threadpool)."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )

    async def generate() -> AsyncGenerator[str, None]:
        tmpdir = Path(tempfile.mkdtemp(prefix="md_gui_"))
        try:
            for upload in files:
                name = upload.filename or "unknown"
                src = tmpdir / name
                try:
                    await _save_upload_streaming(upload, src)
                except ValueError as exc:
                    yield _sse("error", {
                        "file": name,
                        "error": str(exc),
                    })
                    continue

                yield _sse("start", {"file": name})

                # BLK-1: конвертация в threadpool
                try:
                    result = await asyncio.to_thread(
                        _convert_with_capture, src, opts
                    )
                except Exception as exc:
                    yield _sse("error", {
                        "file": name,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue

                md_path = _find_output(src, opts)
                preview = ""
                if md_path and md_path.exists():
                    preview = md_path.read_text(
                        encoding="utf-8"
                    )[:_PREVIEW_CHARS]

                yield _sse("done", {
                    "file": name,
                    "status": result["status"],
                    "log": result["log"],
                    "warnings": result["warnings"],
                    "preview": preview,
                    "output": str(md_path) if md_path else None,
                })
            yield _sse("complete", {})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/convert/url")
async def convert_url_endpoint(
    url: str,
    force: bool = False,
    frontmatter: bool = True,
    keep_images: bool = False,
    pdf_tables: str = "auto",
    only: str | None = None,
    out_dir: str | None = None,
) -> StreamingResponse:
    """Конвертация URL с SSE-прогрессом."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield _sse("start", {"file": url})

        result = await asyncio.to_thread(
            _convert_url_with_capture, url, opts
        )
        stem = core._url_stem(url)
        dest_dir = opts.get("out_dir") or Path.cwd()
        md_path = dest_dir / f"{stem}.md"
        preview = ""
        if md_path.exists():
            preview = md_path.read_text(
                encoding="utf-8"
            )[:_PREVIEW_CHARS]

        yield _sse("done", {
            "file": url,
            "status": result["status"],
            "log": result["log"],
            "warnings": result["warnings"],
            "preview": preview,
            "output": str(md_path) if md_path.exists() else None,
        })
        yield _sse("complete", {})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/convert/path")
async def convert_local_path(
    path: str,
    force: bool = False,
    frontmatter: bool = True,
    keep_images: bool = False,
    pdf_tables: str = "auto",
    only: str | None = None,
    out_dir: str | None = None,
) -> StreamingResponse:
    """Конвертация локального файла по пути (без upload)."""
    src = Path(path).resolve()
    # Path traversal protection
    if not src.exists():
        return JSONResponse(
            {"error": f"File not found: {path}"}, status_code=404
        )
    if ".." in Path(path).parts:
        return JSONResponse(
            {"error": "Path traversal not allowed"},
            status_code=400,
        )

    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )

    async def generate() -> AsyncGenerator[str, None]:
        yield _sse("start", {"file": src.name})

        result = await asyncio.to_thread(
            _convert_with_capture, src, opts
        )
        md_path = _find_output(src, opts)
        preview = ""
        if md_path and md_path.exists():
            preview = md_path.read_text(
                encoding="utf-8"
            )[:_PREVIEW_CHARS]

        yield _sse("done", {
            "file": src.name,
            "status": result["status"],
            "log": result["log"],
            "warnings": result["warnings"],
            "preview": preview,
            "output": str(md_path) if md_path else None,
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
async def download_file(path: str):
    """Скачивание готового .md файла."""
    p = Path(path).resolve()
    if not p.exists() or not p.suffix == ".md":
        return JSONResponse(
            {"error": "File not found"}, status_code=404
        )
    return StreamingResponse(
        p.open("rb"),
        media_type="text/markdown",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{p.name}"'
            )
        },
    )


# --- Cleanup ---

async def _cleanup_loop():
    """G-9: заглушка — jobs хранятся in-memory, очистка не нужна."""
    while True:
        await asyncio.sleep(60)


async def _auto_shutdown_check():
    """Авто-выключение: если вкладка закрыта 15с → shutdown."""
    while True:
        await asyncio.sleep(5)
        if time.time() - _last_heartbeat > 15:
            os.kill(os.getpid(), signal.SIGINT)


# --- Entrypoint ---

def main():
    """Точка входа tomd-gui: старт сервера."""
    global _port
    _port = _find_free_port()
    if sys.stdout.encoding and \
       sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"MD Converter GUI: http://127.0.0.1:{_port}/")
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=_port,
        log_level="warning",
        server_header=False,
    )


if __name__ == "__main__":
    main()
