"""Web-GUI сервер для md-converters.

Запуск: tomd-gui или python -m gui_server
Слушает 127.0.0.1:8765 — только локально, без внешнего доступа.
"""
from __future__ import annotations

import _nostd  # noqa: F401  # ПЕРВЫМ: чинит None-потоки под pythonw
import asyncio
import contextlib
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import webbrowser
import zipfile
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
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
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
    try:
        resolved = p.resolve()
    except OSError as exc:
        raise ValueError(f"Некорректный путь вывода: {exc}") from exc
    # S1: raise ДОЛЖЕН быть вне try — иначе except его же глушит и
    # запретные папки (C:\Windows и т.п.) молча проходят.
    for forbidden in _FORBIDDEN_OUT_DIRS:
        if resolved == forbidden or forbidden in resolved.parents:
            raise ValueError(
                f"Папка вывода не может быть внутри {forbidden}"
            )
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


# --- ③ ZIP-хранилище (папка из браузера → один .zip) ---
_MAX_ZIP_ENTRIES = 5
_ZIP_STORE: OrderedDict[str, tuple[str, bytes]] = OrderedDict()


def _add_zip(zip_id: str, filename: str, data: bytes):
    _ZIP_STORE[zip_id] = (filename, data)
    _ZIP_STORE.move_to_end(zip_id)
    while len(_ZIP_STORE) > _MAX_ZIP_ENTRIES:
        _ZIP_STORE.popitem(last=False)


def _safe_rel(rel_path: str, fallback: str) -> Path:
    """Безопасный ОТНОСИТЕЛЬНЫЙ путь из webkitRelativePath.

    Подпапки сохраняем, '..'/абсолютное/диск-части выкидываем —
    защита от выхода за tmpdir и от zip-slip (имя записи берём
    из md_path.relative_to(tmpdir)).
    """
    parts = []
    for raw in rel_path.replace("\\", "/").split("/"):
        # L-1: вырезаем NUL — на Linux C-рантайм может усечь путь
        raw = raw.replace("\x00", "").strip()
        if raw in ("", ".", "..") or ":" in raw:
            continue
        parts.append(raw)
    if not parts:
        parts = [fallback]
    return Path(*parts)


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
# Открывать браузер и авто-выключаться — ТОЛЬКО при реальном запуске
# (main()). Под TestClient/в тестах эти задачи не нужны: иначе каждый
# тест открывал бы вкладку браузера (если порт 8765 кем-то занят) и
# мог бы сам себя выключить.
_SERVE_MODE = False


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    if _SERVE_MODE:
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

def _host_label(value: str) -> str:
    """Имя хоста из Host/Origin: без порта, lower-case, без скобок
    IPv6 ([::1]:8765 → ::1). Раньше split(':')[0] ломался на IPv6 и
    был регистрозависимым (Localhost → 403)."""
    v = value.strip().lower()
    if v.startswith("["):
        return v[1:].split("]")[0]
    return v.split(":")[0]


@app.middleware("http")
async def _check_origin(request: Request, call_next):
    """BLK-6+S1: отвергаем запросы не с localhost.

    Проверяем И Host, И Origin — браузер ставит Host
    автоматически, но Origin защищает от CSRF с
    соседнего сайта.
    """
    host = _host_label(request.headers.get("host", ""))
    if host not in _ALLOWED_HOSTS:
        return JSONResponse(
            {"error": "forbidden"}, status_code=403
        )
    origin = request.headers.get("origin", "")
    if origin:
        origin_host = _host_label(
            origin.split("//")[-1].split("/")[0]
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
    """H1: только basename — защита от traversal. И / и \\ как
    разделители: загрузка может прийти с Windows-клиента на
    Linux-сервер, где Path(...).name не срежет обратные слэши."""
    base = Path(name.replace("\\", "/").split("/")[-1]).name
    # S6: '.'/'..' как имя указывают на каталог/выше — отбрасываем
    if base in ("", ".", ".."):
        return "unknown"
    return base


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
    verify_ssl: bool = True,
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
        "verify_ssl": verify_ssl,
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


# Конвертации сериализуем процесс-широко: core печатает через
# print(), а _convert_*_with_capture перенаправляет ГЛОБАЛЬНЫЙ
# sys.stdout — два параллельных перехвата затирают друг друга и
# ломают вывод. Плюс общий opts["planned"]/last_target нельзя
# трогать из двух потоков. Один файл за раз — для локального
# однопользовательского GUI этого достаточно.
_CONVERT_LOCK = asyncio.Lock()


async def _run_conversion(fn, arg, opts: dict) -> dict | None:
    """Сериализованная конвертация + точный target от ядра.

    Возвращает dict результата (status/log/warnings/md_path) или
    None, если to_thread бросил исключение наружу.
    """
    async with _CONVERT_LOCK:
        result = await asyncio.to_thread(fn, arg, opts)
        # last_target ставит ядро (convert_file/convert_url) —
        # точная цель записи, без угадывания по stem.
        result["md_path"] = opts.get("last_target")
    return result


def _read_output(md_path: Path | None) -> tuple[str, str]:
    """Читает .md (полностью + превью). Пусто, если файла нет."""
    if md_path and md_path.exists():
        full = md_path.read_text(encoding="utf-8")
        return full, full[:_PREVIEW_CHARS]
    return "", ""


# --- Архивы: распаковать и конвертировать каждый файл → .zip с .md ---
# Поддержка: .zip, .7z, .tar(.gz/.bz2/.xz). RAR не поддерживаем —
# нужен внешний проприетарный бинарник unrar.
_TAR_SUFFIXES = (
    ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
    ".tar.xz", ".txz",
)
# M-1: потолок суммарного РАСПАКОВАННОГО размера 7z (защита от OOM:
# маленький .7z может развернуться в гигабайты).
_MAX_UNCOMPRESSED = 500 * 1024 * 1024


def _archive_kind(path: Path) -> str | None:
    name = path.name.lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(".7z"):
        return "7z"
    if any(name.endswith(s) for s in _TAR_SUFFIXES):
        return "tar"
    return None


def _is_archive(path: Path) -> bool:
    return _archive_kind(path) is not None


def _extract_archive(src: Path, inner: Path) -> None:
    """Распаковывает архив в inner. zip-slip-safe (_safe_rel): имя
    каждого файла санитизируется, запись только внутрь inner. Бросает
    исключение на битом/неподдерживаемом архиве."""
    kind = _archive_kind(src)

    def _write(name: str, reader) -> None:
        dest = inner / _safe_rel(name, "file")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as df:
            shutil.copyfileobj(reader, df)

    if kind == "zip":
        with zipfile.ZipFile(src) as zf:
            for n in zf.namelist():
                if n.endswith("/"):
                    continue
                with zf.open(n) as sf:
                    _write(n, sf)
    elif kind == "tar":
        with tarfile.open(src) as tf:
            for m in tf.getmembers():
                if not m.isfile():
                    continue
                sf = tf.extractfile(m)
                if sf is None:
                    continue
                with sf:
                    _write(m.name, sf)
    elif kind == "7z":
        import py7zr
        # M-1/OOM: сначала проверяем РАСПАКОВАННЫЙ размер по заголовку
        # (без чтения данных) и отвергаем сверх лимита. py7zr 1.x убрал
        # readall(): извлекаем на диск (extractall, без RAM-словаря) в
        # отдельный temp, затем перекладываем в inner через _safe_rel
        # (zip-slip-защита поверх собственной защиты py7zr).
        with py7zr.SevenZipFile(src, "r") as zf:
            total = getattr(zf.archiveinfo(), "uncompressed", 0)
        if total and total > _MAX_UNCOMPRESSED:
            raise ValueError(
                "архив слишком большой в распакованном виде "
                f"({total // (1024 * 1024)} МБ)"
            )
        raw = Path(tempfile.mkdtemp(prefix="md_7z_"))
        try:
            with py7zr.SevenZipFile(src, "r") as zf:
                zf.extractall(path=raw)
            for f in raw.rglob("*"):
                if f.is_file():
                    with f.open("rb") as sf:
                        _write(f.relative_to(raw).as_posix(), sf)
        finally:
            shutil.rmtree(raw, ignore_errors=True)
    else:
        raise ValueError("неподдерживаемый формат архива")


# A-6.3: общий .zip собирается в ОЗУ — ограничиваем, чтобы гигантский
# архив не вызвал OOM. Сверх лимита файлы всё равно конвертируются и
# качаются по одному, но в общий .zip не попадают (с предупреждением).
_MAX_ARCHIVE_FILES = 2000
_MAX_ARCHIVE_BYTES = 300 * 1024 * 1024


async def _convert_archive(src: Path, opts: dict, label: str):
    """Распаковывает архив (.zip/.7z/.tar*), конвертирует каждый файл
    внутри в .md.

    Async-gen: per-member SSE (статус + превью + скачивание по одному),
    затем финальный 'zip'. Если задана out_dir — .md копируются туда;
    иначе собирается ОДИН .zip ТОЛЬКО с .md (без исходников).
    zip-slip-safe (_safe_rel). Вложенные архивы не разворачиваем."""
    inner = Path(tempfile.mkdtemp(prefix="md_unzip_"))
    # Конвертируем ВНУТРИ inner (out_dir=None), копию в out_dir — сами.
    member_opts = dict(opts)
    member_opts["out_dir"] = None
    member_opts["planned"] = set()
    out_dir = opts.get("out_dir")
    collected: list[tuple[str, str]] = []
    total_bytes = 0
    truncated = False
    try:
        try:
            await asyncio.to_thread(_extract_archive, src, inner)
        except Exception as exc:
            yield _sse("error", {
                "file": label,
                "error": f"Не удалось распаковать архив: {exc}",
            })
            yield _sse("zip", {"zip_id": "", "count": 0})
            return
        scan = opts.get("scan") or core.SUPPORTED_SUFFIXES
        files = await asyncio.to_thread(
            core.collect, str(inner), True, scan
        )
        files = [f for f in files if not _is_archive(f)]
        for member in files:
            yield _sse("start", {"file": member.name})
            try:
                res = await _run_conversion(
                    _convert_with_capture, member, member_opts
                )
            except Exception as exc:
                yield _sse("error", {
                    "file": member.name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            md_path = res["md_path"]
            full, preview = _read_output(md_path)
            dl_id = ""
            out_path = None
            if full and md_path:
                rel = md_path.relative_to(inner)
                dl_id = uuid.uuid4().hex[:12]
                _add_download(dl_id, md_path.name, full)
                if out_dir is not None:
                    dest = out_dir / rel
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(full, encoding="utf-8")
                        out_path = str(dest)
                    except OSError:
                        out_path = None
                elif (len(collected) < _MAX_ARCHIVE_FILES
                      and total_bytes + len(full)
                      <= _MAX_ARCHIVE_BYTES):
                    collected.append((rel.as_posix(), full))
                    total_bytes += len(full)
                else:
                    truncated = True
            yield _sse("done", {
                "file": member.name,
                "status": res["status"],
                "log": res["log"],
                "warnings": res["warnings"],
                "preview": preview,
                "download_id": dl_id,
                "output": out_path,
            })
        # Общий .zip только с .md — если выходная папка НЕ задана
        zip_id = ""
        if collected and out_dir is None:
            buf = io.BytesIO()
            with zipfile.ZipFile(
                buf, "w", zipfile.ZIP_DEFLATED
            ) as zf:
                for entry, content in collected:
                    zf.writestr(entry, content)
            zip_id = uuid.uuid4().hex[:12]
            _add_zip(zip_id, src.stem + "_md.zip", buf.getvalue())
        if truncated:
            yield _sse("error", {
                "file": label,
                "error": (
                    "Архив слишком большой — в общий .zip вошла "
                    "только часть. Остальные файлы доступны по одному "
                    "или задайте «Папку вывода»."
                ),
            })
        yield _sse("zip", {
            "zip_id": zip_id, "count": len(collected),
            "truncated": truncated,
        })
    finally:
        shutil.rmtree(inner, ignore_errors=True)


# --- ② Нативный выбор файла/папки с диска (конвертация на месте) ---

# Запускается отдельным процессом: tkinter + uvicorn в одном loop
# конфликтуют, а подпроцесс изолирует диалог. Путь возвращается
# через файл в UTF-8 (среда кириллическая — не через stdout).
_PICKER_CODE = '''\
import sys, json
import tkinter as tk
from tkinter import filedialog
kind, outfile = sys.argv[1], sys.argv[2]
root = tk.Tk()
root.withdraw()
try:
    root.attributes("-topmost", True)
except tk.TclError:
    pass
root.update()
if kind == "folder":
    p = filedialog.askdirectory(
        title="Папка для конвертации в Markdown")
    res = [p] if p else []
else:
    res = list(filedialog.askopenfilenames(
        title="Файлы для конвертации в Markdown"))
root.destroy()
with open(outfile, "w", encoding="utf-8") as f:
    json.dump(res, f)
'''


def _has_tkinter() -> bool:
    """tkinter доступен? (на голом Linux-CI его может не быть)."""
    return importlib.util.find_spec("tkinter") is not None


def _native_pick(kind: str) -> list[str]:
    """Открывает родной диалог ОС и возвращает выбранные пути.

    Путь приходит ТОЛЬКО из диалога, никогда из HTTP-запроса —
    поэтому endpoint не даёт сторонней странице подсунуть путь
    (важно вместе с S1/CSRF). Пусто = отмена/ошибка.
    """
    fd, outfile = tempfile.mkstemp(suffix=".json", prefix="md_pick_")
    os.close(fd)
    sd, script = tempfile.mkstemp(suffix=".py", prefix="md_pick_")
    os.close(sd)
    try:
        Path(script).write_text(_PICKER_CODE, encoding="utf-8")
        subprocess.run(
            [sys.executable, script, kind, outfile],
            timeout=300, capture_output=True,
        )
        data = Path(outfile).read_text(encoding="utf-8")
        return json.loads(data) if data.strip() else []
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    finally:
        for p in (outfile, script):
            with contextlib.suppress(OSError):
                os.unlink(p)


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
    """Конвертация файлов с SSE-прогрессом (последовательно)."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
    )
    has_out_dir = opts.get("out_dir") is not None

    async def generate() -> AsyncGenerator[str, None]:
        tmpdir = Path(tempfile.mkdtemp(prefix="md_gui_"))
        try:
            # 1. Загрузка (последовательно — это поток upload)
            jobs = []
            for upload in files:
                name = _safe_filename(
                    upload.filename or "unknown"
                )
                src = tmpdir / name
                try:
                    await _save_upload_streaming(upload, src)
                except (ValueError, OSError) as exc:
                    yield _sse("error", {
                        "file": name, "error": str(exc),
                    })
                    continue
                yield _sse("start", {"file": name})
                jobs.append((src, name))

            # 2. Конвертация по одному файлу за раз
            for src, name in jobs:
                # архив (.zip/.7z/.tar*) → распаковать и конвертировать
                if _is_archive(src):
                    async for ev in _convert_archive(
                        src, opts, name
                    ):
                        yield ev
                    continue
                try:
                    res = await _run_conversion(
                        _convert_with_capture, src, opts
                    )
                except Exception as exc:
                    yield _sse("error", {
                        "file": name,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                md_path = res["md_path"]
                full_content, preview = _read_output(md_path)
                dl_id = ""
                if full_content:
                    dl_id = uuid.uuid4().hex[:12]
                    _add_download(
                        dl_id, md_path.name, full_content
                    )
                yield _sse("done", {
                    "file": name,
                    "status": res["status"],
                    "log": res["log"],
                    "warnings": res["warnings"],
                    "preview": preview,
                    "download_id": dl_id,
                    # Реальный путь показываем, только если он
                    # стабилен (out_dir задан); иначе tmp удалится.
                    "output": (
                        str(md_path)
                        if has_out_dir and md_path else None
                    ),
                })
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
    insecure_ssl: bool = Form(False),
) -> StreamingResponse:
    """Конвертация URL с SSE-прогрессом."""
    opts = _gui_opts(
        force, frontmatter, keep_images,
        pdf_tables, only, out_dir,
        verify_ssl=not insecure_ssl,
    )

    has_out_dir = opts.get("out_dir") is not None

    async def generate() -> AsyncGenerator[str, None]:
        yield _sse("start", {"file": url})
        try:
            res = await _run_conversion(
                _convert_url_with_capture, url, opts
            )
        except Exception as exc:
            yield _sse("error", {
                "file": url,
                "error": f"{type(exc).__name__}: {exc}",
            })
            yield _sse("complete", {})
            return

        md_path = res["md_path"]
        full_content, preview = _read_output(md_path)
        dl_id = ""
        if full_content:
            dl_id = uuid.uuid4().hex[:12]
            _add_download(dl_id, md_path.name, full_content)

        yield _sse("done", {
            "file": url,
            "status": res["status"],
            "log": res["log"],
            "warnings": res["warnings"],
            "preview": preview,
            "download_id": dl_id,
            "output": (
                str(md_path)
                if has_out_dir and md_path else None
            ),
        })
        yield _sse("complete", {})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/convert/picked")
async def convert_picked(
    kind: str = Form("files"),
    force: bool = Form(False),
    frontmatter: bool = Form(True),
    keep_images: bool = Form(False),
    pdf_tables: str = Form("auto"),
    only: str | None = Form(None),
) -> StreamingResponse:
    """② Выбор файла/папки родным диалогом → конвертация НА МЕСТЕ.

    .md пишется рядом с исходником (out_dir не задаётся). Путь
    берётся только из диалога ОС, не из HTTP-запроса.
    """
    want = "folder" if kind == "folder" else "files"
    opts = _gui_opts(
        force, frontmatter, keep_images, pdf_tables, only, None,
    )

    async def generate() -> AsyncGenerator[str, None]:
        if not _has_tkinter():
            yield _sse("error", {
                "file": "—",
                "error": (
                    "tkinter недоступен — выбор с диска невозможен"
                ),
            })
            yield _sse("complete", {})
            return
        picked = await asyncio.to_thread(_native_pick, want)
        if not picked:
            yield _sse("cancelled", {})
            yield _sse("complete", {})
            return
        if want == "folder":
            files = await asyncio.to_thread(
                core.collect, picked[0], True, opts["scan"]
            )
        else:
            files = [Path(p) for p in picked]
        if not files:
            yield _sse("error", {
                "file": picked[0],
                "error": "Подходящих файлов не найдено",
            })
            yield _sse("complete", {})
            return
        for src in files:
            # архив (.zip/.7z/.tar*) → распаковать и конвертировать
            if _is_archive(src):
                async for ev in _convert_archive(
                    src, opts, src.name
                ):
                    yield ev
                continue
            yield _sse("start", {"file": src.name})
            try:
                res = await _run_conversion(
                    _convert_with_capture, src, opts
                )
            except Exception as exc:
                yield _sse("error", {
                    "file": src.name,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue
            md_path = res["md_path"]
            full_content, preview = _read_output(md_path)
            dl_id = ""
            if full_content:
                dl_id = uuid.uuid4().hex[:12]
                _add_download(dl_id, md_path.name, full_content)
            yield _sse("done", {
                "file": src.name,
                "status": res["status"],
                "log": res["log"],
                "warnings": res["warnings"],
                "preview": preview,
                "download_id": dl_id,
                "output": str(md_path) if md_path else None,
            })
        yield _sse("complete", {})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.post("/api/convert/zip")
async def convert_zip(
    files: list[UploadFile],
    paths: str = Form("[]"),
    force: bool = Form(False),
    frontmatter: bool = Form(True),
    keep_images: bool = Form(False),
    pdf_tables: str = Form("auto"),
    only: str | None = Form(None),
) -> StreamingResponse:
    """③ Папка из браузера → один .zip с .md (структура сохранена).

    Относительные пути приходят отдельным JSON-полем paths
    (параллельно files), НЕ в имени файла — его H1 срезает до
    basename. Дерево зеркалится в tmpdir, .md пишется на месте,
    имя записи zip = md_path относительно tmpdir.
    """
    opts = _gui_opts(
        force, frontmatter, keep_images, pdf_tables, only, None,
    )
    try:
        rel_paths = json.loads(paths)
        if not isinstance(rel_paths, list):
            rel_paths = []
    except ValueError:
        rel_paths = []

    async def generate() -> AsyncGenerator[str, None]:
        tmpdir = Path(tempfile.mkdtemp(prefix="md_zip_"))
        collected: list[tuple[str, str]] = []
        try:
            jobs = []
            for i, upload in enumerate(files):
                base = _safe_filename(
                    upload.filename or f"file{i}"
                )
                rel = rel_paths[i] if i < len(rel_paths) else base
                src = tmpdir / _safe_rel(rel, base)
                try:
                    await _save_upload_streaming(upload, src)
                except (ValueError, OSError) as exc:
                    yield _sse("error", {
                        "file": rel, "error": str(exc),
                    })
                    continue
                yield _sse("start", {"file": rel})
                jobs.append((src, rel))
            for src, rel in jobs:
                try:
                    res = await _run_conversion(
                        _convert_with_capture, src, opts
                    )
                except Exception as exc:
                    yield _sse("error", {
                        "file": rel,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    continue
                md_path = res["md_path"]
                full_content, preview = _read_output(md_path)
                if full_content and md_path:
                    entry = md_path.relative_to(tmpdir).as_posix()
                    collected.append((entry, full_content))
                yield _sse("done", {
                    "file": rel,
                    "status": res["status"],
                    "log": res["log"],
                    "warnings": res["warnings"],
                    "preview": preview,
                    "download_id": "",
                })
            zip_id = ""
            if collected:
                buf = io.BytesIO()
                with zipfile.ZipFile(
                    buf, "w", zipfile.ZIP_DEFLATED
                ) as zf:
                    for entry, content in collected:
                        zf.writestr(entry, content)
                zip_id = uuid.uuid4().hex[:12]
                _add_zip(zip_id, "markdown.zip", buf.getvalue())
            yield _sse("zip", {
                "zip_id": zip_id, "count": len(collected),
            })
            yield _sse("complete", {})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return StreamingResponse(
        generate(), media_type="text/event-stream",
    )


@app.get("/api/download_zip")
async def download_zip(zip_id: str):
    """③ Скачивание собранного .zip из памяти."""
    entry = _ZIP_STORE.get(zip_id)
    if not entry:
        return JSONResponse(
            {"error": "not found"}, status_code=404
        )
    filename, data = entry
    encoded = quote(filename, safe="")
    return StreamingResponse(
        iter([data]),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{encoded}\"; "
                f"filename*=UTF-8''{encoded}"
            )
        },
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
    global _port, _uvicorn_server, _SERVE_MODE
    _SERVE_MODE = True  # только тут включаем браузер + авто-выключение
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
