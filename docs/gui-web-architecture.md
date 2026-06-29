# Архитектура Web-GUI для md-converters (вариант 1, ревизия 2)

> Локальный веб-сервер (FastAPI) + браузер как интерфейс.
> Пользователь запускает ярлык → открывается браузер с drag-and-drop
> зоной и превью. Сервер слушает только `127.0.0.1` — это не интернет-
> сервис, а локальное приложение.

**Ревизия 2:** добавлены 7 блокаторов (threading, race conditions,
безопасность), 12 пробелов (cancel, localStorage, port retry),
модель состояния Job, защита от DNS rebinding.

> ⚠️ Это **проектный документ до реализации** (дизайн-спека). Макеты и
> названия кнопок здесь — эскизные и местами расходятся с финальной
> реализацией (часть идей вроде «тёмной темы» и «Отмена» не делалась).
> Актуальная справка по интерфейсу и реальным лейблам — в
> [`gui-guide.md`](gui-guide.md) и в самом GUI; контракт фронтенда —
> в [`gui-contract.md`](gui-contract.md).

---

## 0. Блокаторы (обязательно к реализации)

Эти 7 проблем делают наивную реализацию неработоспособной или опасной.
Каждая должна быть закрыта в коде.

### BLK-1: `convert_file` — блокирующий вызов в event loop

`convert_file` синхронный, вызывает `subprocess.run` (sandbox), работает
30–60 секунд. Если вызвать прямо в `async def` — **заблокирует весь
event loop**: `/api/heartbeat`, `/api/preview`, SSE-стрим — всё встанет.

**Фикс:** обработчик `def` (не `async def`) — FastAPI запускает в
threadpool. Или `anyio.to_thread.run_sync(convert_file, ...)` внутри
async-обработчика.

### BLK-2: Браузер открывается ДО готовности сервера

`webbrowser.open()` в `lifespan` срабатывает до того, как uvicorn начал
слушать порт. Браузер → `connection refused` → страница ошибки.

**Фикс:** фоновая задача ждёт готовности порта (retry 20×0.5с), потом
открывает браузер. См. §3.7.

### BLK-3: Конфликт порта 8765

Порт занят (предыдущий запуск, другое приложение) → uvicorn падает с
`OSError`. Пользователь видит трейсбек.

**Фикс:** последовательный перебор 8765, 8766, 8767… (до 5 попыток).
Первый свободный → используется; передаётся в `webbrowser.open`.

### BLK-4: `opts["planned"]` — разделяемое состояние

`_build_opts` создаёт `"planned": set()`. Два одновременных запроса →
общий set → гонки, конфликты имён.

**Фикс:** создавать **новый** opts на каждый запрос. Не кэшировать opts
между запросами.

### BLK-5: Upload 100 МБ в память

`await file.read()` грузит файл целиком в RAM. 10 файлов по 100 МБ →
1 ГБ → OOM.

**Фикс:** потоковое сохранение чанками по 1 МБ (§3.5).

### BLK-6: DNS rebinding — malicious website → localhost

Злонамеренный сайт отправляет `fetch("http://127.0.0.1:8765/api/
convert/path", {body: "C:\\...\\secrets"})`. Same-Origin Policy не
защищает localhost. Сервер конвертирует и возвращает содержимое →
**утечка данных**.

**Фикс:** middleware проверяет `Host` / `Origin` на каждом запросе.
Отвергать, если не `127.0.0.1:8765` / `localhost:8765`. См. §6.2.

### BLK-7: `marked.js` рендерит `<script>` → XSS в превью

Документ содержит `<script>alert(1)</script>`. `sanitize_markdown`
чистит вне fences, но внутри fences (после фикса M-PDF-01) сохраняет.
`marked.js` отрендерит → **XSS**.

**Фикс:** после `marked.js` — `DOMPurify.sanitize(html)`. См. §4.3.

---

## 1. Принцип

```
┌──────────────────────────────────────────────────────────────┐
│  Пользователь                                                │
│                                                              │
│  ┌─────────────┐          ┌──────────────────────────────┐   │
│  │  Браузер    │ ←SSE─── │  FastAPI (127.0.0.1:8765)    │   │
│  │  (frontend) │ ──POST→ │  gui_server.py               │   │
│  └─────────────┘          └──────────┬───────────────────┘   │
│                                      │ import                  │
│                          ┌───────────▼───────────────────┐   │
│                          │  convert_to_md.py             │   │
│                          │  convert_file / convert_url   │   │
│                          │  (вызов в threadpool)         │   │
│                          └───────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

Сервер — тонкий слой: принимает файлы/URL → передаёт в существующие
функции `convert_file` / `convert_url` / `run` → возвращает результат.
**Ноль дублирования логики конвертации.**

### Threading model (явно)

```
Event loop (asyncio / uvicorn)
  ├── GET /, /api/flags, /api/heartbeat     — мгновенно, async
  ├── GET /api/preview/{id}, /download/{id} — мгновенно, async
  └── POST /api/convert/files               — DELEGATES to threadpool:
        └── anyio.to_thread.run_sync(convert_file)
            └── subprocess.run (--_worker-convert)  ← sandbox
```

Конвертация ВСЕГДА в threadpool — не блокирует event loop.

---

## 2. Новые файлы

```
md-converters/
├── convert_to_md.py          ← существующий, НЕ меняется
├── gui_server.py             ← НОВЫЙ: FastAPI (~400 строк)
├── gui_static/
│   ├── index.html            ← НОВЫЙ: страница (~350 строк)
│   ├── marked.min.js         ← НОВЫЙ: Markdown-рендер (40 КБ)
│   └── purify.min.js         ← НОВЫЙ: XSS-фильтр (20 КБ)
├── pyproject.toml            ← дополнить: tomd-gui + [gui] deps
├── install.ps1               ← дополнить: ярлык для GUI
└── tests/
    └── test_gui.py           ← НОВЫЙ: TestClient (~150 строк)
```

---

## 3. gui_server.py — архитектура

### 3.1. Структура

```python
"""Web-GUI сервер для md-converters.

Запуск: tomd-gui или python -m gui_server
Слушает 127.0.0.1:8765 — только локально, без внешнего доступа.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import signal
import socket
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator

import uvicorn
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import (
    HTMLResponse, JSONResponse, StreamingResponse, FileResponse,
)

import convert_to_md as core

_STATIC = Path(__file__).parent / "gui_static"
_PORT_DEFAULT = 8765
_PORT_TRIES = 5
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 МБ
_MAX_JOBS = 20
_JOB_TTL = 30 * 60  # 30 минут

_ALLOWED_HOSTS = {"127.0.0.1", "localhost"}


# --- Модель задачи (BLK-4: per-request state, G-9: TTL) ---

@dataclass
class Job:
    id: str
    source: str                       # имя файла / URL
    status: str = "pending"           # pending/running/ok/skip/fail/cancelled
    output_path: Path | None = None
    preview: str | None = None
    log: str = ""
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None  # для отмены

_jobs: dict[str, Job] = {}
_last_heartbeat = time.time()


# --- Жизненный цикл ---

@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    global _port
    _port = _find_free_port()
    # BLK-2: браузер после готовности порта
    asyncio.create_task(_open_browser_when_ready(_port))
    # G-9: очистка старых jobs
    asyncio.create_task(_cleanup_loop())
    yield
    _cleanup_all()

app = FastAPI(lifespan=_lifespan)
```

### 3.2. Поиск свободного порта (BLK-3)

```python
def _find_free_port() -> int:
    """BLK-3: перебор портов 8765, 8766, ..."""
    for offset in range(_PORT_TRIES):
        port = _PORT_DEFAULT + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in {_PORT_DEFAULT}–{_PORT_DEFAULT + _PORT_TRIES - 1}")
```

### 3.3. Открытие браузера после готовности (BLK-2)

```python
async def _open_browser_when_ready(port: int) -> None:
    """Ждём пока uvicorn начнёт слушать, потом открываем браузер."""
    for _ in range(20):  # 10 секунд максимум
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            webbrowser.open(f"http://127.0.0.1:{port}/")
            return
        except (ConnectionError, OSError):
            await asyncio.sleep(0.5)
```

### 3.4. Middleware: DNS rebinding protection (BLK-6)

```python
@app.middleware("http")
async def _check_origin(request: Request, call_next):
    """BLK-6: отвергаем запросы не с localhost."""
    host = request.headers.get("host", "").split(":")[0]
    if host not in _ALLOWED_HOSTS:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return await call_next(request)
```

### 3.5. Потоковое сохранение upload (BLK-5)

```python
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
                raise HTTPException(413, "File too large")
            f.write(chunk)
    return total
```

### 3.6. Перехват stdout/stderr

```python
def _convert_with_capture(path: Path, opts: dict) -> dict:
    """Конвертация с перехватом stdout/stderr."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        status = core.convert_file(path, opts)
    return {"status": status, "log": out.getvalue(), "warnings": err.getvalue()}
```

### 3.7. Адаптер opts (BLK-4: per-request)

```python
def _gui_opts(force: bool, frontmatter: bool, keep_images: bool,
              pdf_tables: str, only_spec: str | None,
              out_dir: str | None = None) -> dict:
    """BLK-4: новый opts на каждый запрос."""
    parsed = {
        "force": force, "frontmatter": frontmatter,
        "keep_images": keep_images,
        "unsafe_raw_markdown": False, "allow_private_url": False,
        "url_timeout": str(core._DEFAULT_URL_TIMEOUT),
        "max_url_mb": str(core._DEFAULT_MAX_URL_MB),
        "max_input_mb": str(core._DEFAULT_MAX_INPUT_MB),
        "conversion_timeout": str(core._DEFAULT_CONVERSION_TIMEOUT),
        "sandbox": True, "out_dir": Path(out_dir) if out_dir else None,
        "mirror": False,
        "only": core._suffix_set(only_spec) if only_spec else None,
        "pdf_tables": pdf_tables, "errors": [],
    }
    return core._build_opts(parsed, default_only=None)
```

### 3.8. SSE-streaming конвертация (BLK-1: threadpool)

```python
@app.post("/api/convert/files")
async def convert_files(
    files: list[UploadFile],
    force: bool = False, frontmatter: bool = True,
    keep_images: bool = False, pdf_tables: str = "auto",
    only: str | None = None, out_dir: str | None = None,
) -> StreamingResponse:
    """Конвертация с потоковым выводом прогресса (SSE)."""
    opts = _gui_opts(force, frontmatter, keep_images,
                     pdf_tables, only, out_dir)

    async def generate() -> AsyncGenerator[str, None]:
        tmpdir = Path(tempfile.mkdtemp(prefix="md_gui_"))
        try:
            for upload in files:
                src = tmpdir / upload.filename
                await _save_upload_streaming(upload, src)
                _sse_send("start", {"file": upload.filename})

                # BLK-1: конвертация в threadpool — не блокирует event loop
                result = await anyio.to_thread.run_sync(
                    _convert_with_capture, src, opts
                )
                # читаем готовый .md
                md_path = _find_output(src, opts)
                preview = md_path.read_text(encoding="utf-8")[:5000] if md_path else ""

                _sse_send("done", {
                    "file": upload.filename,
                    "status": result["status"],
                    "log": result["log"],
                    "preview": preview,
                    "output": str(md_path) if md_path else None,
                })
            _sse_send("complete", {})
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return StreamingResponse(generate(), media_type="text/event-stream")
```

### 3.9. Heartbeat и авто-выключение

```python
@app.post("/api/heartbeat")
async def heartbeat():
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"ok": True}

async def _auto_shutdown_check():
    """Фоновая задача: если вкладка закрыта 15с → shutdown."""
    while True:
        await asyncio.sleep(5)
        if time.time() - _last_heartbeat > 15:
            os.kill(os.getpid(), signal.SIGINT)
```

### 3.10. Очистка jobs (G-9)

```python
async def _cleanup_loop():
    """G-9: удаляем jobs старше _JOB_TTL каждые 60с."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired = [jid for jid, j in _jobs.items()
                   if now - j.created_at > _JOB_TTL]
        for jid in expired:
            _jobs.pop(jid, None)
```

### 3.11. Точка входа

```python
def main():
    """Точка входа tomd-gui: старт сервера."""
    uvicorn.run(
        app, host="127.0.0.1", port=_find_free_port(),
        log_level="warning", server_header=False,
    )

if __name__ == "__main__":
    main()
```

---

## 4. gui_static/index.html — frontend

### 4.1. Структура страницы

```
┌─────────────────────────────────────────────────────────────┐
│  md-converters v1.3.0              [☐ тёмная тема]          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │           📎  Перетащите файлы сюда                   │  │
│  │           или нажмите «Выбрать»                       │  │
│  │       PDF, HTML, DOCX, XLSX, PPTX, CSV, JSON          │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Настройки (сохраняются в localStorage) ────────────┐    │
│  │  [x] YAML front-matter   [ ] Сохранить картинки      │    │
│  │  [ ] Перезаписать (force) [x] Извлекать PDF-таблицы  │    │
│  │  Форматы: [все ▼]   Папка вывода: [____________]     │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Или URL ───────────────────────────────────────────┐    │
│  │  https://example.com/report              [→ Конверт.]│    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Результаты ────────────────────────────────────────┐    │
│  │  ✅ report.pdf → report.md      [Превью] [Скачать]   │    │
│  │  ⏳ big-report.pdf ... Converting... [Отмена]        │    │
│  │  ⏭️  existing.md — пропущен                          │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─ Превью Markdown (marked.js + DOMPurify) ───────────┐    │
│  │  <отрендеренный Markdown>                             │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 4.2. State machine (G-11: frontend state)

```
idle → uploading → converting → done
                            ↘ error
                            ↘ cancelled
```

Каждое состояние — свой набор кнопок и индикаторов.

### 4.3. Превью: marked.js + DOMPurify (BLK-7)

```html
<script src="marked.min.js"></script>
<script src="purify.min.js"></script>
<script>
async function showPreview(mdText) {
    // BLK-7: marked.js рендерит, DOMPurify чистит от XSS
    const raw = marked.parse(mdText);
    const clean = DOMPurify.sanitize(raw);
    document.getElementById("preview").innerHTML = clean;
}
</script>
```

### 4.4. localStorage настроек (G-5)

```javascript
// Сохранение при изменении
function saveSettings() {
    const settings = {
        force: document.getElementById("force").checked,
        frontmatter: document.getElementById("frontmatter").checked,
        keepImages: document.getElementById("keep-images").checked,
        pdfTables: document.getElementById("pdf-tables").value,
        outDir: document.getElementById("out-dir").value,
    };
    localStorage.setItem("md-converters-settings", JSON.stringify(settings));
}

// Восстановление при загрузке
function loadSettings() {
    const saved = localStorage.getItem("md-converters-settings");
    if (saved) {
        const s = JSON.parse(saved);
        document.getElementById("force").checked = s.force;
        // ...
    }
}
```

### 4.5. Heartbeat (авто-выключение сервера)

```javascript
// Каждые 5 секунд — heartbeat (сервер жив, пока вкладка открыта)
setInterval(() => fetch("/api/heartbeat", {method: "POST"}), 5000);
```

### 4.6. SSE-клиент

```javascript
async function convertFiles(files) {
    const formData = new FormData();
    files.forEach(f => formData.append("files", f));
    // ... добавляем флаги

    const response = await fetch("/api/convert/files", {
        method: "POST", body: formData,
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        // Парсим SSE-события (разделитель \n\n)
        const events = buffer.split("\n\n");
        buffer = events.pop();  // неполный — в буфер
        for (const evt of events) {
            const data = JSON.parse(evt.replace(/^data: /, ""));
            handleSSE(data);  // обновляем UI по событию
        }
    }
}
```

### 4.7. Проверка размера до upload (G-6)

```javascript
function checkFileSize(file) {
    if (file.size > 100 * 1024 * 1024) {
        alert(`Файл ${file.name}: ${(file.size / 1048576).toFixed(0)} МБ — лимит 100 МБ`);
        return false;
    }
    return true;
}
```

### 4.8. Esc = отмена (G-1, G-11)

```javascript
document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") cancelConversion();
});
```

---

## 5. Интеграция с существующим кодом

### 5.1. Что переиспользуется без изменений

| Функция в `convert_to_md.py` | Использование в GUI |
|---|---|
| `convert_file(path, opts)` | Конвертация (в threadpool) |
| `convert_url(url, opts)` | Конвертация URL (в threadpool) |
| `run(items, opts)` | Пакетная обработка |
| `_build_opts(parsed, default_only)` | Сборка opts |
| `_plan_file_target` / `_plan_url_target` | Имена выходных файлов |
| `tidy` / `sanitize_markdown` | Внутри convert_file |
| `__version__` | Отображение в шапке |
| `SUPPORTED_SUFFIXES` | Подсказка в drop-zone |

### 5.2. Что НЕ меняется в `convert_to_md.py`

**Ничего.** Сервер только импортирует и вызывает.

---

## 6. Безопасность

### 6.1. Сетевая изоляция

| Параметр | Значение | Почему |
|---|---|---|
| `host` | `127.0.0.1` | Сервер недоступен из сети |
| `port` | 8765+ (перебор) | BLK-3: конфликт-резистентный |
| CORS | отключён | Браузер на том же хосте |
| HTTPS | не нужен | Локальный трафик не покидает машину |

### 6.2. Защита от атак

| Угроза | Митигация | Код |
|---|---|---|
| DNS rebinding (BLK-6) | Middleware: проверка Host/Origin | `_check_origin` |
| Path traversal | Валидация пути: `.resolve()`, без `..` | в `/api/convert/path` |
| Upload > 100 МБ | Потоковая проверка размера | `_save_upload_streaming` |
| XSS в превью (BLK-7) | DOMPurify после marked.js | frontend |
| Выполнение кода | Sandbox (subprocess) включён | `opts["sandbox"]=True` |
| SSRF через URL | `_check_url_allowed` (per-hop) | внутри `convert_url` |
| Утечка jobs | TTL 30 мин, max 20 записей | `_cleanup_loop` |

---

## 7. Запуск и установка

### 7.1. Новая точка входа в `pyproject.toml`

```toml
[project.scripts]
tomd = "convert_to_md:cli_tomd"
pdf2md = "convert_to_md:cli_pdf"
html2md = "convert_to_md:cli_html"
tomd-gui = "gui_server:main"           # ← НОВЫЙ

[project.optional-dependencies]
gui = [
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.32,<1.0",
    "python-multipart>=0.0.12,<1.0",
]
```

GUI — **опциональная** зависимость:

```bash
pip install ".[gui]"
```

Без `[gui]` — только CLI, как раньше.

### 7.2. Ярлык в `install.ps1`

```powershell
$hasGui = & $python -c "import fastapi" 2>$null
if ($LASTEXITCODE -eq 0) {
    $guiLnk = $Desktop.JoinPath("MD Converter.lnk")
    $sc = $WScriptShell.CreateShortcut($guiLnk)
    $sc.TargetPath = $python
    $sc.Arguments = '-m gui_server'
    $sc.WorkingDirectory = $kit
    $sc.IconLocation = Join-Path $kit "convert.ico"
    $sc.Save()
}
```

### 7.3. Авто-выключение

Frontend шлёт `/api/heartbeat` каждые 5с. Если 15с тишины → сервер
выключается (`SIGINT`).

---

## 8. Пользовательские сценарии

### 8.1. Конвертация одного PDF

1. Двойной клик «MD Converter» → браузер открылся
2. Перетащить `report.pdf` → файл проверен (< 100 МБ)
3. Нажать «Конвертировать»
4. Прогресс: «Converting report.pdf...» (SSE)
5. Результат: ✅ `report.pdf → report.md`
6. Клик «Превью» → Markdown с таблицами (marked.js + DOMPurify)
7. Клик «Скачать» → файл сохранён

### 8.2. Пакетная конвертация

1. Перетащить 10 файлов
2. Настройки: `[x] force`
3. Результаты по каждому (SSE):
   ✅ `report1.pdf → report1.md`
   ⏳ `big-report.pdf ...` (с кнопкой «Отмена»)
   ⏭️ `existing.md — пропущен`

### 8.3. Конвертация URL

1. Вставить URL → Enter
2. Прогресс: «Downloading…» → «Converting…»
3. Результат: ✅ `page.md`

### 8.4. Конвертация локального файла (без upload)

1. Нажать «Указать путь»
2. Вставить путь или выбрать в диалоге
3. Сервер читает напрямую с диска
4. `.md` рядом с источником

---

## 9. Объём работ (ревизия 2)

| Компонент | Строк | Время |
|---|---|---|
| `gui_server.py` (FastAPI + Job model + BLK-1..7) | ~400 | 6–8 ч |
| `gui_static/index.html` (state machine + SSE + localStorage) | ~350 | 6–8 ч |
| `marked.min.js` + `purify.min.js` | 60 КБ | 30 мин |
| `pyproject.toml` + entry point | ~15 | 30 мин |
| `install.ps1` (дополнение) | ~20 | 1 ч |
| `tests/test_gui.py` (TestClient + SSE + origin + path) | ~150 | 3–4 ч |
| README (раздел GUI) | ~50 | 1 ч |
| **Итого** | **~1000 + 60 КБ** | **20–28 ч** |

### Этапы

| Этап | Что | Результат |
|---|---|---|
| **1. Core** | gui_server.py: FastAPI, BLK-1/3/4/5/6, SSE, threadpool | Сервер работает, файлы конвертируются |
| **2. Frontend** | index.html: drop-zone, SSE-клиент, флаги, список результатов | Полноценный UI |
| **3. Превью** | marked.js + DOMPurify (BLK-7), скачивание, path-режим | Production UX |
| **4. Интеграция** | install.ps1, heartbeat (BLK-2), авто-выключение, localStorage (G-5), тёмная тема | Готов к релизу |

---

## 10. Что НЕ делать

- Не заменять CLI — GUI это дополнение
- Не менять `convert_to_md.py` — только импортировать
- Не делать multi-user — локальное приложение
- Не добавлять auth — 127.0.0.1, пароль не нужен
- Не тянуть React/Vue — vanilla JS достаточен
- Не делать PyInstaller .exe — onnxruntime/magika (~200 МБ, сломается)

---

## 11. Чеклист реализации (для loop)

### Этап 1 — Core (BLK-1, BLK-3, BLK-4, BLK-5, BLK-6)

- [ ] `_find_free_port()` — перебор 8765–8769
- [ ] `_check_origin` middleware — Host/Origin на 127.0.0.1/localhost
- [ ] `_save_upload_streaming()` — чанки 1 МБ, лимит 100 МБ
- [ ] `_convert_with_capture()` — redirect_stdout/stderr
- [ ] `_gui_opts()` — per-request opts builder
- [ ] `POST /api/convert/files` — SSE + `anyio.to_thread.run_sync`
- [ ] `POST /api/convert/url` — SSE + threadpool
- [ ] `GET /api/flags` — значения по умолчанию
- [ ] `GET /` — отдаёт index.html
- [ ] `main()` — uvicorn.run на свободном порту
- [ ] `pyproject.toml`: `[gui]` deps + `tomd-gui` entry point
- [ ] Тест: TestClient → upload → статус ok

### Этап 2 — Frontend (BLK-1, G-6, G-11)

- [ ] `gui_static/index.html` — drop-zone, file input
- [ ] SSE-клиент (fetch + ReadableStream)
- [ ] Список результатов с статусами (✅ ⏳ ⏭️ ❌)
- [ ] Чекбоксы: force, frontmatter, keep-images, pdf-tables
- [ ] Поле only (форматы)
- [ ] Проверка размера файла до upload (G-6)
- [ ] Кнопка «Отмена» (Esc) — G-1
- [ ] Базовый CSS (тёмная тема)

### Этап 3 — Превью (BLK-7, G-2, G-3, G-4)

- [ ] Скачать `marked.min.js` + `purify.min.js` в `gui_static/`
- [ ] Превью: `marked.parse()` → `DOMPurify.sanitize()` → innerHTML
- [ ] Переключение между результатами (G-2)
- [ ] Кнопка «Скачать .md» — `GET /api/download/{path}`
- [ ] Кнопка «Открыть папку» — `POST /api/open-folder`
- [ ] `POST /api/convert/path` — локальный файл без upload
- [ ] Поле «Папка вывода» (G-3)

### Этап 4 — Интеграция (BLK-2, G-5, G-9, G-12)

- [ ] `_open_browser_when_ready()` — retry порта (BLK-2)
- [ ] `/api/heartbeat` + `_auto_shutdown_check()` (G-9)
- [ ] `_cleanup_loop()` — TTL jobs 30 мин
- [ ] `localStorage` настроек (G-5)
- [ ] `install.ps1` — ярлык «MD Converter»
- [ ] README — раздел GUI
- [ ] `tests/test_gui.py` — TestClient, SSE, origin-check, path-traversal
- [ ] `uv run ruff check gui_server.py` чист
- [ ] `uv run pytest -q` зелёные
