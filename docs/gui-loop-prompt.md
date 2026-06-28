# Loop-промт: реализация Web-GUI для md-converters

> Скопируй текст ниже и запусти как `/loop <текст>`.
> Канон архитектуры — `docs/gui-web-architecture.md` (ревизия 2).

---

Реализуй Web-GUI для проекта md-converters. Проект — в `V:\md-converters`. Канон архитектуры — `docs/gui-web-architecture.md` (ревизия 2). Окружение: Python 3.14, Windows, cmd.exe, `uv run` для запуска, ruff line-length=79, коммиты на русском по Conventional Commits, трейлер `Co-Authored-By: Qwen Code <noreply@anthropic.com>`. После каждого шага — `git add -A && commit && push` в main.

**Нельзя менять `convert_to_md.py`** — только импортировать из него. GUI — опциональная зависимость (`[gui]`), без неё CLI работает как прежде.

**7 блокаторов — обязательны к закрытию:**
1. `convert_file` синхронный → вызывать через `anyio.to_thread.run_sync` (не блокировать event loop)
2. Браузер открывается ДО готовности порта → фоновая задача ждёт соединения, потом `webbrowser.open`
3. Конфликт порта → перебор 8765, 8766, 8767 (до 5 попыток через `socket.bind`)
4. `opts["planned"]` — общий set → создавать новый opts на каждый запрос
5. Upload 100 МБ в память → потоковое сохранение чанками по 1 МБ
6. DNS rebinding → middleware проверяет `Host` на `127.0.0.1`/`localhost`, иначе 403
7. XSS через `<script>` в превью → после `marked.js` обязательно `DOMPurify.sanitize`

**Цикл каждой итерации:**
1. Прочитай `docs/gui-web-architecture.md` — это канон.
2. `git status -sb` и `git log --oneline -5` — определи, что готово.
3. Найди следующий незакрытый этап (1→2→3→4) и реализуй ОДИН шаг из него.

**Этап 1 — Ядро сервера (блокаторы 1, 3, 4, 5, 6):**
- `gui_server.py`: FastAPI, `_find_free_port`, `_check_origin` middleware, `_save_upload_streaming`, `_convert_with_capture`, `_gui_opts`, `POST /api/convert/files` (SSE + threadpool), `POST /api/convert/url`, `GET /api/flags`, `GET /` (отдаёт index.html), `main()` — uvicorn на свободном порту.
- `pyproject.toml`: секция `[project.optional-dependencies] gui` с fastapi/uvicorn/python-multipart; entry point `tomd-gui = "gui_server:main"`.
- Базовый `gui_static/index.html` — drop-zone, кнопки, список результатов (просто `<pre>` для превью, без marked.js пока).

**Этап 2 — Интерфейс (блокатор 1, пункты G-6, G-11):**
- CSS (тёмная тема, моноширинный шрифт). Чекбоксы всех флагов (force, frontmatter, keep-images, pdf-tables, only). Поле папки вывода. Проверка размера файла ДО загрузки (G-6). Кнопка «Отмена» и Esc (G-1). SSE-клиент на fetch + ReadableStream.

**Этап 3 — Превью и пути (блокатор 7, пункты G-2, G-3, G-4):**
- Скачай `marked.min.js` и `purify.min.js` в `gui_static/`. Превью: `marked.parse()` → `DOMPurify.sanitize()`. Переключение между результатами (G-2). Кнопки «Скачать .md» и «Открыть папку». `POST /api/convert/path` — локальный файл без upload.

**Этап 4 — Интеграция (блокатор 2, пункты G-5, G-9, G-12):**
- `_open_browser_when_ready` (retry порта). `/api/heartbeat` + авто-выключение через 15с тишины (SIGINT). `_cleanup_loop` — TTL jobs 30 мин, max 20. `localStorage` настроек (G-5). Дополнение `install.ps1` — ярлык «MD Converter». Раздел в README. Тесты `tests/test_gui.py` (TestClient: upload, convert, SSE, origin-check, path-traversal).

**Проверка после каждого шага:**
- `uv run ruff check gui_server.py` (строки ≤79)
- `uv run python -m py_compile gui_server.py`
- `uv run pytest -q` (существующие 107 тестов не должны сломаться)

**Условие выхода:** все 4 этапа закрыты, блокаторы 1–7 реализованы, ruff чист, pytest зелёные, `install.ps1` обновлён, README дополнен. Тогда — закрой loop.
