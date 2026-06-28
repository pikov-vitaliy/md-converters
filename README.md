# Конвертеры документов → Markdown

[![CI](https://github.com/pikov-vitaliy/md-converters/actions/workflows/ci.yml/badge.svg)](https://github.com/pikov-vitaliy/md-converters/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Версия: **1.3.0**.

Универсальный инструмент перевода документов в Markdown. Одна команда `tomd`
понимает формат по расширению и конвертирует **что угодно**:

| Что | Форматы |
|-----|---------|
| Документы | PDF, **Word `.docx`**, **Excel `.xlsx`**, **PowerPoint `.pptx`** |
| Веб/данные | HTML, URL веб-страницы, CSV, JSON, XML, RSS, EPUB |
| Прочее | Outlook `.msg`, Jupyter `.ipynb`, изображения (EXIF/OCR) |

Под капотом — [MarkItDown](https://github.com/microsoft/markitdown) от Microsoft.
Результат по умолчанию кладётся **рядом с исходником**: то же имя, расширение
`.md` (или в отдельную папку — флаг `-o`). При совпадении имён результата
(например, `report.docx` и `report.pdf` рядом) добавляется суффикс `(2)`.

Команды-синонимы для привычки: `pdf2md` (только PDF) и `html2md` (только HTML)
— это тот же `tomd` с фильтром формата.

---

## Содержимое папки

```
md-converters\
├─ convert_to_md.py        — основной скрипт (вся логика)
├─ install.ps1             — установщик (зависимости + команды + Send To)
├─ pyproject.toml          — для установки через pip (кроссплатформенно)
├─ uv.lock                 — lockfile зависимостей для разработки/CI
├─ convert.ico             — иконка пунктов контекстного меню
├─ icon-source.png         — исходник иконки для tools\make_icon.py
├─ tools\                  — служебные проверки SCA/лицензий
├─ README.md              — эта инструкция
├─ LICENSE                — MIT
├─ .github\workflows\     — CI (GitHub Actions, смоук-тест)
└─ examples\
   ├─ sample-report.html  — пример входного отчёта
   └─ sample-report.md    — как он выглядит после конвертации
```

---

## Быстрый старт (Windows)

1. Откройте **PowerShell** в этой папке (в Проводнике: правый клик по пустому
   месту внутри папки → «Открыть в терминале»).
2. Выполните установщик:

   ```powershell
   pwsh -ExecutionPolicy Bypass -File .\install.ps1
   ```

3. Откройте **новое** окно PowerShell (чтобы команды подхватились).
4. Проверьте:

   ```powershell
   tomd .\examples\sample-report.html
   ```

Готово — рядом появится `sample-report.md`.

---

## Как пользоваться

| Команда | Что делает |
|---------|------------|
| `tomd` | спросит файл, папку, маску или URL |
| `tomd отчёт.docx` | один файл (расширение можно не писать) |
| `tomd a.pdf b.xlsx c.html` | несколько файлов любых форматов |
| `tomd *` | все поддерживаемые документы в текущей папке |
| `tomd C:\reports` | все документы в указанной папке |
| `tomd C:\reports -r` | то же, плюс все вложенные папки |
| `tomd *.pdf -f` | перезаписать уже существующие `.md` |
| `tomd C:\reports -r -o C:\vault` | результат сложить в одну папку (база знаний) |
| `tomd C:\reports -r -o C:\vault --mirror` | сохранить структуру подпапок в `C:\vault` |
| `tomd https://site/page` | конвертировать веб-страницу по URL |
| `tomd https://site/page --url-timeout 10 --max-url-mb 20` | URL с лимитами |
| `tomd http://127.0.0.1:8000 --allow-private-url` | локальный URL явно |
| `tomd папка --only docx,xlsx` | брать только Word и Excel |
| `tomd отчёт.pdf --pdf-tables off` | без извлечения таблиц из PDF |
| `tomd отчёт.docx --keep-images` | оставить картинки как base64 |
| `tomd отчёт.html --unsafe-raw-markdown` | не очищать опасные ссылки/HTML |
| `tomd отчёт.pdf --max-input-mb 200 --conversion-timeout 300` | лимиты файла |
| `tomd отчёт.pdf --no-sandbox` | без отдельного worker-процесса |
| `tomd отчёт.html --no-frontmatter` | без YAML-шапки |
| `tomd --version` | показать версию утилиты |
| `tomd --help` | полная справка |

```text
PS C:\reports> tomd *
Конвертирую vulnerability-report.html ...
Готово: C:\reports\vulnerability-report.md
Конвертирую асессмент.docx ...
Готово: C:\reports\асессмент.md
Конвертирую реестр.xlsx ...
Готово: C:\reports\реестр.md
Итого: сконвертировано 3 из 3.
```

`pdf2md` и `html2md` работают так же, но при маске/папке берут только свой
формат: `pdf2md *` — все PDF в папке, `html2md C:\site -r` — только HTML.

### Правый клик в Проводнике (без терминала)

По умолчанию установщик `install.ps1` **спрашивает** после установки,
добавлять ли пункты в контекстное меню — это изменение системного
состояния, и без явного согласия мы их не создаём. Если отвечаете «Y»,
после установки в Проводнике появятся:

- **Send to → «Конвертировать в Markdown»** (правый клик → Отправить).
- **Open with → «Конвертировать в Markdown»** (правый клик → Открыть
  с помощью) — Win11 22H2+ рядом с WinRAR / VS Code / Notepad++.
- **Show more options → «Конвертировать в Markdown»** — в Win11; в Win10
  пункт виден сразу в коротком меню.

Все записи — в `HKCU\Software\Classes\...`, без админ-прав, только для
текущего пользователя. Идемпотентно: переустановка с `-NoMenu` снимает
записи, переустановка с `-Menu` восстанавливает.

#### Режимы установки

```powershell
# По умолчанию (без флагов) — интерактивный вопрос после установки.
pwsh -ExecutionPolicy Bypass -File .\install.ps1

# Сразу добавить пункты в контекстное меню (без вопроса):
pwsh -ExecutionPolicy Bypass -File .\install.ps1 -Menu

# Установить только команды, контекстное меню не трогать (CI / минимальная):
pwsh -ExecutionPolicy Bypass -File .\install.ps1 -NoMenu
```

---

## Web-GUI (опционально)

Для тех, кто предпочитает графический интерфейс консоли, есть локальный
веб-GUI на базе FastAPI — drag-and-drop зона, настройки, превью Markdown
с подсветкой таблиц и кода.

### Установка

```bash
pip install ".[gui]"
```

Или через `install.ps1` — если fastapi уже установлен, ярлык «MD Converter»
создаётся на рабочем столе автоматически.

### Запуск

```bash
tomd-gui          # старт сервера + авто-открытие браузера
```

Двойной клик по ярлыку «MD Converter» — браузер открывается с
интерфейсом. Закрыли вкладку — сервер выключается автоматически (через
15 секунд).

### Возможности

- **Drag-and-drop** файлов или ввод URL
- Настройки: front-matter, перезапись, картинки, PDF-таблицы, форматы
- **Превью** Markdown (marked.js + DOMPurify — защита от XSS)
- Скачивание результата
- Настройки сохраняются между запусками (localStorage)
- Сервер слушает только `127.0.0.1` — недоступен из сети

---

## Что получится (фрагмент `examples\sample-report.md`)

```markdown
---
title: "Пример отчёта об уязвимостях — demo-project"
source: "sample-report.html"
source_name: "sample-report.html"
source_path: "examples\\sample-report.html"
source_id: "path:..."
converted: 2026-06-10
generator: tomd 1.3.0 (MarkItDown)
---

# Отчёт об уязвимостях — demo-project

## Находки

| Пакет | Уровень | Описание | Исправление |
| --- | --- | --- | --- |
| left-pad | критический | Удалённое выполнение кода | обновить до 1.3.0 |
```

---

## Встроенные защиты и удобства

### 1. Защита от перезаписи

Если рядом уже есть `.md`, файл **не перезаписывается молча** — он пропускается:

```text
[пропуск] report.md уже есть (-f / --force для перезаписи)
Итого: сконвертировано 0 из 2, пропущено 2.
```

Так не потеряются правки, внесённые в `.md` руками. Перезаписать — флаг `-f` /
`--force`. В интерактивном режиме утилита спросит один раз на всю пачку:

```text
2 файл(ов) уже имеют .md. Перезаписать? (y = да / Enter = пропустить):
```

### 2. Пропуск служебных папок при `-r`

При рекурсии (`-r`) утилита **не заходит** в служебные каталоги, где обычно
лежат сотни ненужных файлов: `node_modules`, `.git`, `.next`, `dist`, `build`,
`venv`, `.venv`, `__pycache__`, `.idea` и т. п.

### 3. Папка вывода `-o`

`-o C:\vault` складывает все `.md` в одну папку вместо «рядом с исходником» —
удобно конвертировать дерево отчётов прямо в базу знаний / Obsidian.

При совпадении имён результата добавляется суффикс `(2)`, `(3)` — это
работает и без `-o`: `report.docx` и `report.pdf` в одной папке дадут
`report.md` и `report (2).md`, а не затрут друг друга.

Если важна исходная структура папок, добавьте `--mirror` (или
`--preserve-tree`):

```powershell
tomd C:\students -r -o C:\vault --mirror
```

Тогда `C:\students\ivanov\курсовая.docx` попадёт в
`C:\vault\ivanov\курсовая.md`, а `C:\students\petrov\курсовая.docx` — в
`C:\vault\petrov\курсовая.md`. Это удобнее для пачек отчётов, курсовых и
проектных папок, где одноимённые документы лежат в разных каталогах.

### 4. Автоопределение кодировки (HTML)

Если инструмент выдал HTML в `windows-1251` без правильного `<meta charset>`,
кириллица **не превратится в «кракозябры»** — кодировка определяется
автоматически:

```text
Готово: C:\reports\gost-report.md (перекодировано из cp1251)
```

### 5. Сворачивание встроенных картинок

Word/HTML часто вставляют картинки прямо в документ как огромные base64-строки.
По умолчанию они заменяются компактным плейсхолдером `![...]()`, чтобы `.md`
оставался читаемым. Из PowerPoint картинки не извлекаются вовсе — MarkItDown
пишет ссылку на несуществующий файл (`![](Picture5.jpg)`), и просмотрщики
рисуют вместо неё ошибку `EntryNotFound` / `ENOENT`; такие ссылки-заглушки
тоже сворачиваются в плейсхолдер. Нужно как было — флаг `--keep-images`.

Заодно из текста убираются невидимые управляющие символы: например,
перенос строки внутри абзаца PowerPoint (vertical tab), который в `.md`
выглядел бы «квадратиком», заменяется обычным пробелом.

### 6. YAML front-matter

В начало каждого `.md` добавляется блок с источником и датой — удобно для базы
знаний / Obsidian:

```yaml
---
title: "Заголовок документа"
source: "имя-исходного-файла.docx"
source_name: "имя-исходного-файла.docx"
source_path: "путь\\к\\имя-исходного-файла.docx"
source_id: "path:короткий-хэш-источника"
converted: 2026-06-10
generator: tomd 1.3.0 (MarkItDown)
---
```

`title` берётся из заголовка документа (если есть), `source_id` помогает
повторно сопоставлять одноимённые файлы из разных папок при выводе через
`-o`, `generator` показывает, какой командой сделан файл. Отключить —
флаг `--no-frontmatter`.

### 7. Безопасная очистка Markdown

По умолчанию утилита нейтрализует опасные ссылки и raw HTML, которые могли
попасть из исходного HTML/документа в Markdown: `javascript:`, `vbscript:`,
`file:`, опасные `data:`-ссылки, inline-обработчики вроде `onclick`/`onerror`
и теги `script`/`iframe`/`object`/`embed`/`style`.

Это защита от случайного открытия вредного Markdown в Obsidian, VS Code
preview, статическом сайте или LMS. Она снижает риск, но не заменяет ручную
проверку перед публикацией материалов наружу.

Если источник полностью доверенный и нужно сохранить сырой Markdown как есть,
используйте `--unsafe-raw-markdown`.

### 8. Безопасный URL-режим

URL загружаются с защитами по умолчанию:

- разрешены только `http` и `https`;
- `localhost`, `127.0.0.0/8`, `::1`, private/link-local/multicast и другие
  непубличные адреса блокируются;
- каждый редирект проверяется заново;
- сетевой timeout по умолчанию — 20 секунд;
- максимум ответа по умолчанию — 50 МБ;
- переменные окружения proxy не используются для этой загрузки.

Для осознанного локального сценария есть флаг `--allow-private-url`, например
при конвертации страницы локального отчёта с `http://127.0.0.1:8000`.

Лимиты меняются флагами `--url-timeout SEC` и `--max-url-mb MB`.

### 9. Лимиты локальных файлов

Локальные документы по умолчанию конвертируются в отдельном worker-процессе.
Это помогает ограничить зависший или слишком тяжёлый парсер одного файла и
продолжить пакетную обработку следующих документов.

Защиты по умолчанию:

- максимум размера локального файла — 100 МБ;
- timeout конвертации одного файла — 120 секунд;
- при превышении лимита файл помечается ошибкой, остальные файлы продолжают
  обрабатываться.

Лимиты меняются флагами `--max-input-mb MB` и `--conversion-timeout SEC`.
Флаг `--no-sandbox` оставлен для доверенных сценариев и отладки: он запускает
конвертацию локального файла в основном процессе.

### 10. Чистка вывода и сводка

Markdown прибирается (хвостовые пробелы, лишние пустые строки, края). На пачке
печатается итог, а всё, что не удалось, перечисляется отдельно:

```text
Итого: сконвертировано 2 из 3, ошибок 1.
Не удалось обработать:
  - C:\reports\битый-файл.pdf
```

---

## Модель безопасности

`md-converters` рассчитан на локальный запуск доверенным пользователем, но
входные документы, HTML и URL считаются потенциально недоверенными. Это важно
для сценариев с материалами от студентов, подрядчиков, внешних LMS, отчётов
сканеров и выгрузок из неизвестных систем.

Защитная модель по умолчанию:

- локальные файлы проверяются по размеру до передачи стороннему парсеру;
- конвертация локального файла идёт в отдельном worker-процессе с timeout;
- URL разрешены только по `http`/`https`, private/loopback/link-local адреса
  блокируются, редиректы проверяются повторно;
- сетевые ответы читаются с timeout и ограничением размера;
- выходной Markdown очищается от опасных схем ссылок и raw HTML;
- существующие `.md` не перезаписываются без `--force`.

Ограничения:

- worker-процесс не является полноценной ОС-песочницей с отдельным
  пользователем, seccomp/AppContainer или контейнером;
- утилита снижает риск активного содержимого в Markdown, но не заменяет
  редакторскую проверку перед публикацией в LMS, статический сайт или базу
  знаний;
- `--allow-private-url`, `--unsafe-raw-markdown`, `--no-sandbox` следует
  использовать только для доверенных локальных сценариев.

Для обработки особо недоверенных файлов используйте отдельную виртуальную
машину или контейнер без доступа к чувствительным каталогам и внутренним
сетям. Это соответствует принципам least privilege и defense-in-depth
(NIST SSDF PW.4/PW.8, OWASP SSRF Prevention, CWE-400/CWE-918).

---

## Особенности форматов

- **Таблицы.** HTML, Word (`.docx`) и Excel (`.xlsx`) хранят настоящую
  структуру таблиц — они переводятся в аккуратные Markdown-таблицы. У Word
  есть мелкий нюанс: верхняя строка-заголовок может выйти пустой, а сами
  заголовки встанут первой строкой тела (данные при этом все на месте).
- **PDF — таблицы через pdfplumber (по геометрии).** Для PDF таблицы
  извлекаются по геометрии страницы (линии/края заливок) библиотекой
  `pdfplumber`, а не по координатам слов, как делает штатный путь
  MarkItDown. Это надёжно переводит разлинованные и безбордюрные таблицы в
  аккуратные Markdown-таблицы, отделяя их от прозы (текст и таблицы идут по
  порядку чтения, без дублирования). Утилита склеивает таблицы,
  перенесённые на следующую страницу (по повтору строки-заголовка), и
  отбрасывает ложные «таблицы» из прозы. В front-matter пишется число
  извлечённых таблиц: `pdf_tables: N`. Отключить и вернуться к штатному
  тексту MarkItDown — флаг `--pdf-tables off`. Предел метода: полностью
  «голые» таблицы без линий и фона и сканы (нет геометрии) — там результат
  по-прежнему best-effort; для них помогает только OCR/ML-извлекатель.
  Ещё один edge: строка таблицы, разорванная между страницами посреди
  ячейки, восстанавливается не полностью.
- **Псевдографика таблиц (`│┌┬┐├┼┤└┴┘─`) → Markdown.** Таблицы, нарисованные
  символами рамок прямо в тексте (часто их вставляют генераторы/ИИ),
  распознаются и конвертируются в нормальные Markdown-таблицы (иначе в
  Markdown-вьюере они разъезжаются). Работает для любого формата, на обычный
  текст и на готовые таблицы с ASCII-`|` не влияет.
- **Код, команды и конфиги из PDF → код-блоки (` ``` `).** Строки команд
  (`sudo …`, `lsblk -f`), SQL (`CREATE …`), конфигов (`wal_level = logical`),
  путей и вывода оборачиваются в код-блоки. Иначе плейсхолдеры `<…>`
  съедаются вьюером как HTML-теги, `#`-комментарии становятся заголовками, а
  строки вывода (`|-vda2 …`) ломаются как таблицы. Распознавание построчное
  (русская проза не трогается); настоящие таблицы не оборачиваются.
- **PDF без текстового слоя (сканы).** Если PDF — это отсканированные
  страницы без OCR, MarkItDown извлечёт пустой или мусорный Markdown.
  Утилита это распознаёт: печатает в stderr жёлтое предупреждение
  `[warning] file.pdf: PDF without a text layer ...` и помечает
  результат в front-matter как `pdf_text_layer: absent`. Сам файл `.md`
  при этом создаётся, чтобы не блокировать пакетную обработку. Для
  распознавания откройте PDF в ABBYY FineReader или запустите
  `ocrmypdf file.pdf file-ocr.pdf` (нужен установленный Tesseract) и
  сконвертируйте `file-ocr.pdf` заново — тогда получите
  `pdf_text_layer: present`.
- **Картинки.** Встроенные картинки (base64) по умолчанию сворачиваются в
  плейсхолдер `![...]()`, чтобы `.md` оставался читаемым. Из PowerPoint
  (`.pptx`) сами файлы картинок не извлекаются — битые ссылки-заглушки
  также заменяются плейсхолдером. Флаг `--keep-images` оставляет всё как
  выдал MarkItDown.

---

## Перенос на другой компьютер

1. **Скопируйте всю папку** `md-converters` куда удобно. Путь любой —
   установщик пропишет команды на то место, куда вы её положили.

2. **Установите Python 3.10+** (если ещё нет): скачайте с
   <https://www.python.org/downloads/>, при установке поставьте галочку
   **«Add python.exe to PATH»**. Проверка: `python --version`.

3. **Запустите установщик** из папки комплекта:

   ```powershell
   pwsh -ExecutionPolicy Bypass -File .\install.ps1
   ```

   Он сам: найдёт Python → поставит актуальный комплект `md-converters`
   из текущей папки вместе с зависимостями → пропишет команды
   `tomd` / `pdf2md` / `html2md` → спросит, добавлять ли пункты в
   контекстное меню Проводника (Send to, Open with, Show more options) →
   проверит на примере.

4. **Откройте новое окно PowerShell** и пользуйтесь.

Установщик можно запускать повторно — старые строки он убирает и прописывает
заново.

### Вариант через pip (любая ОС: Windows / macOS / Linux)

```bash
pip install .
tomd path/to/file.docx
```

Команды `tomd`, `pdf2md`, `html2md` появятся как обычные консольные утилиты
(пункт Send To — только для Windows, через `install.ps1`).

---

## Разработка, SBOM и SCA

Для разработки используется `uv.lock`: он фиксирует транзитивные зависимости
для поддерживаемых Python 3.10-3.14 и платформ Windows/Linux. Это нужно для
воспроизводимости поставки, SCA и лицензионного контроля.

Базовый цикл проверки:

```powershell
python -m pip install "uv>=0.11,<0.12"
uv sync --frozen
uv run --frozen tomd --version
uv run --frozen python -m py_compile convert_to_md.py tools/supply_chain_report.py
uv run --frozen ruff check convert_to_md.py tests tools
uv run --frozen pytest -q
```

Проверка состава поставки:

```powershell
uv lock --check
uv --quiet export --format requirements.txt --no-dev --no-emit-project --locked --output-file requirements-runtime-audit.txt
uv --quiet export --format requirements.txt --all-groups --no-emit-project --locked --output-file requirements-dev-audit.txt
uv --quiet export --format cyclonedx1.5 --no-dev --locked --output-file cyclonedx-runtime-sbom.json
uv --quiet export --format cyclonedx1.5 --all-groups --locked --output-file cyclonedx-dev-sbom.json
uv sync --frozen --no-dev
uv run --frozen --no-dev python tools/supply_chain_report.py --output supply-chain-licenses.json --fail-on-forbidden
uv run --frozen pip-audit --progress-spinner off -r requirements-runtime-audit.txt
uv run --frozen pip-audit --progress-spinner off -r requirements-dev-audit.txt
```

Что получается:

- `cyclonedx-runtime-sbom.json` — CycloneDX SBOM по runtime-зависимостям;
- `cyclonedx-dev-sbom.json` — CycloneDX SBOM для среды разработки
  (runtime + dev tools);
- `requirements-runtime-audit.txt` — lock-экспорт runtime-графа для
  `pip-audit`;
- `requirements-dev-audit.txt` — lock-экспорт development-графа для
  `pip-audit`;
- `supply-chain-licenses.json` — инвентаризация лицензий из metadata
  установленных runtime-пакетов.

В CI эти файлы публикуются как артефакты job `supply-chain`. Локальные
одноразовые SBOM/отчёты можно пересоздавать перед передачей комплекта или
аудитом; исходники проверок (`uv.lock`, `tools/`, workflow) хранятся в
репозитории.

Файлы, сгенерированные в корне репозитория (`cyclonedx-*.json`,
`requirements-*-audit.txt`, `supply-chain-licenses.json`), в `.gitignore`
добавлены в ignore — случайный локальный прогон SCA не осядет коммитом
мимо схемы. «Бумажный след» официальных аудитов релиза хранится
централизованно в `docs/vibe-audit/evidence/<ГГГГ-ММ-ДД>/` — по одной
подпапке на дату.

Идеи развития, которые не вошли в текущую версию (OCR сканов, пресет «для проверки
студенческих работ», выкидывание `.msg` из зависимостей), собраны в
`docs/vibe-audit/future-ideas.md` — заметки на будущее, не план.

Политика лицензий по умолчанию блокирует сильный copyleft и лицензии с
нежелательными ограничениями: AGPL/GPL/LGPL, SSPL, Commons Clause, Sleepycat.
`UNKNOWN` пока считается замечанием для ручной проверки, а не автоматическим
падением сборки.

Dependabot настроен для еженедельных PR по Python-зависимостям и GitHub
Actions. Обновления должны проходить через тот же CI: lockfile, тесты, SBOM,
`pip-audit` и лицензионная проверка.

---

## Если что-то пошло не так

**`install.ps1 нельзя запустить, политика выполнения...`**
Запускайте с обходом политики только для этого файла:
```powershell
pwsh -ExecutionPolicy Bypass -File .\install.ps1
```

**`Python не найден`** — установите Python с галочкой «Add to PATH» и запустите
установщик снова. Заглушку из Microsoft Store установщик игнорирует.

**Команды не находятся** — откройте **новое** окно PowerShell или выполните
`. $PROFILE`.

**Изменили расположение папки или обновили Python** — запустите `install.ps1`
ещё раз из новой папки.

**В Send to видна шестерёнка вместо иконки** — пересоздайте пункты меню:
```powershell
pwsh -ExecutionPolicy Bypass -File .\install.ps1 -Menu
```
Установщик явно записывает `convert.ico` в `IconLocation` ярлыка. Если
Проводник держит старый кэш, перезапустите `explorer.exe` или выйдите из
Windows и войдите снова.

**Excel/Word не конвертируются** — нужна установка зависимостей с
формат-экстрами (это делает установщик):
`python -m pip install "markitdown[pdf,docx,pptx,xlsx,xls,outlook]>=0.1.0,<1.0.0"`.

---

## Удаление

1. Откройте профиль: `notepad $PROFILE` и удалите блок между
   `# >>> md-converters >>>` и `# <<< md-converters <<<`.
2. Удалите ярлык «Конвертировать в Markdown» из папки
   `shell:sendto` (Win+R → `shell:sendto`).
3. При желании: `python -m pip uninstall markitdown` и удалите папку комплекта.

---

## Что нужно для работы (кратко)

- **Python 3.10+** (на Windows — с галочкой «Add to PATH»).
- Пакет **`markitdown[pdf,docx,pptx,xlsx,xls,outlook]`** (0.1.x) — ставится
  установщиком автоматически. Не `[all]`: на Python 3.14 из-за него pip
  молча откатывается на древний markitdown 0.0.2.
- Для команд и пункта Send To на Windows — **PowerShell 7.2+** (`pwsh`,
  ставится: `winget install Microsoft.PowerShell`).

---

## In English

`md-converters` is a universal **document → Markdown** tool built on
[MarkItDown](https://github.com/microsoft/markitdown). One command — `tomd` —
detects the format by extension and converts PDF, HTML, Word (`.docx`),
Excel (`.xlsx`), PowerPoint (`.pptx`), CSV, JSON, XML, EPUB, Outlook `.msg`,
Jupyter notebooks, RSS, and web pages by URL.

**Install (Windows):** run `install.ps1` (PowerShell 7.2+) — it installs
`markitdown[pdf,docx,pptx,xlsx,xls,outlook]>=0.1.0,<1.0.0`, registers the
`tomd` / `pdf2md` / `html2md` commands in your PowerShell profile, and
**prompts** whether to add a right-click *Send to → Convert to Markdown*
entry plus the corresponding entries in the main context menu (`Open with`
in Windows 11 22H2+, `Show more options` in Windows 11 / direct menu in
Windows 10). Pass `-Menu` to install without the prompt, or `-NoMenu` to
install commands only (no registry changes). All context menu entries are
in `HKCU\Software\Classes\...` — no admin rights required.

**Install (any OS):** `pip install .` exposes `tomd`, `pdf2md`, `html2md`.

**Usage:**

```text
tomd report.docx                # one file (output next to it)
tomd *                          # every document in the folder
tomd C:\reports -r -o C:\vault  # whole tree into one folder
tomd C:\reports -r -o C:\vault --mirror  # preserve folders under vault
tomd https://site/page          # a web page
tomd folder --only docx,xlsx    # filter by type
tomd report.pdf --pdf-tables off  # disable PDF table extraction
```

Glob / folder / recursive input (skips `node_modules`, `.git`), overwrite
protection (`-f`), YAML front-matter, HTML encoding auto-detection, base64
image collapsing (`--keep-images` keeps raw), tidy output, and a summary with
a list of failures. `pdf2md` / `html2md` are the same tool restricted to one
format. Tables convert cleanly from HTML / Word / Excel; PDF tables are
extracted by geometry via `pdfplumber` (cross-page joins, prose filtering,
`pdf_tables: N` in front-matter; `--pdf-tables off` to disable). Fully
borderless tables and scans remain best-effort.
