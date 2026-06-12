# Конвертеры документов → Markdown

[![CI](https://github.com/pikov-vitaliy/md-converters/actions/workflows/ci.yml/badge.svg)](https://github.com/pikov-vitaliy/md-converters/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

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
| `tomd https://site/page` | конвертировать веб-страницу по URL |
| `tomd https://site/page --url-timeout 10 --max-url-mb 20` | URL с лимитами |
| `tomd http://127.0.0.1:8000 --allow-private-url` | локальный URL явно |
| `tomd папка --only docx,xlsx` | брать только Word и Excel |
| `tomd отчёт.docx --keep-images` | оставить картинки как base64 |
| `tomd отчёт.html --unsafe-raw-markdown` | не очищать опасные ссылки/HTML |
| `tomd отчёт.pdf --max-input-mb 200 --conversion-timeout 300` | лимиты файла |
| `tomd отчёт.pdf --no-sandbox` | без отдельного worker-процесса |
| `tomd отчёт.html --no-frontmatter` | без YAML-шапки |
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

После установки выделите один или несколько файлов в Проводнике →
правый клик → **Отправить** → **Конвертировать в Markdown**. Откроется окно
с ходом конвертации; `.md` появятся рядом с исходниками.

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
generator: tomd (MarkItDown)
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
generator: tomd (MarkItDown)
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
- **PDF — таблицы ненадёжно.** В PDF нет структуры таблиц, только текст с
  координатами на странице. Поэтому таблица из PDF может выйти и нормальной
  Markdown-таблицей, и обычным текстом построчно — как повезёт с конкретным
  файлом. Это ограничение самого формата PDF, а не утилиты. Если для каких-то
  PDF таблицы критичны, можно подключить отдельный извлекатель
  (pdfplumber / camelot) — скажите, добавлю.
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

   Он сам: найдёт Python → поставит `markitdown` → пропишет команды
   `tomd` / `pdf2md` / `html2md` → добавит пункт «Отправить → Конвертировать в
   Markdown» → проверит на примере.

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
uv run --frozen python -m py_compile convert_to_md.py tools/supply_chain_report.py
uv run --frozen ruff check convert_to_md.py tests tools
uv run --frozen pytest -q
```

Проверка состава поставки:

```powershell
uv lock --check
uv --quiet export --format requirements.txt --no-dev --no-emit-project --locked --output-file requirements-audit.txt
uv --quiet export --format cyclonedx1.5 --no-dev --locked --output-file cyclonedx-sbom.json
uv sync --frozen --no-dev
uv run --frozen --no-dev python tools/supply_chain_report.py --output supply-chain-licenses.json --fail-on-forbidden
uvx pip-audit --progress-spinner off -r requirements-audit.txt
```

Что получается:

- `cyclonedx-sbom.json` — CycloneDX SBOM по runtime-зависимостям;
- `requirements-audit.txt` — lock-экспорт для `pip-audit`;
- `supply-chain-licenses.json` — инвентаризация лицензий из metadata
  установленных runtime-пакетов.

В CI эти файлы публикуются как артефакты job `supply-chain`. Локальные
одноразовые SBOM/отчёты можно пересоздавать перед передачей комплекта или
аудитом; исходники проверок (`uv.lock`, `tools/`, workflow) хранятся в
репозитории.

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
`tomd` / `pdf2md` / `html2md` commands in your PowerShell profile, and adds
a right-click *Send to → Convert to Markdown* entry.

**Install (any OS):** `pip install .` exposes `tomd`, `pdf2md`, `html2md`.

**Usage:**

```text
tomd report.docx                # one file (output next to it)
tomd *                          # every document in the folder
tomd C:\reports -r -o C:\vault  # whole tree into one folder
tomd https://site/page          # a web page
tomd folder --only docx,xlsx    # filter by type
```

Glob / folder / recursive input (skips `node_modules`, `.git`), overwrite
protection (`-f`), YAML front-matter, HTML encoding auto-detection, base64
image collapsing (`--keep-images` keeps raw), tidy output, and a summary with
a list of failures. `pdf2md` / `html2md` are the same tool restricted to one
format. Tables convert cleanly from HTML / Word / Excel; PDF tables are
best-effort (PDF stores no table structure).
