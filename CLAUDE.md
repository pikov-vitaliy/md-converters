# CLAUDE.md — контекст проекта для AI-агентов

Этот файл — онбординг для Claude Code и любых AI-агентов. Прочитай его
первым, чтобы сразу быть в контексте проекта. Язык проекта — русский
(интерфейс утилит, README, комментарии). Пользователь: Виталий Пиков
(vitaliy@pikov.com), сфера — DevSecOps / безопасность; конвертирует
отчёты инструментов (SBOM, уязвимости, ГОСТ/РБПО-аудит) в Markdown для
базы знаний.

## Что это

**md-converters** — утилита перевода документов в Markdown на базе
[MarkItDown](https://github.com/microsoft/markitdown) (Microsoft). Одна
команда `tomd` определяет формат по расширению и конвертирует: PDF, HTML,
Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`), CSV, JSON, XML,
EPUB, Outlook `.msg`, Jupyter, RSS и веб-страницы по URL.

## Где что лежит

- **GitHub:** https://github.com/pikov-vitaliy/md-converters — **private**,
  ветка по умолчанию `main`. Аккаунт `pikov-vitaliy` (через `gh`).
- **Локальная рабочая копия (канон):** `V:\md-converters`. Все git-операции
  делай отсюда: `git -C "V:\md-converters" ...`.
- **Устаревшая копия:** `C:\Users\user\Documents\md-converters` — НЕ
  используется командами, осталась как след ранней итерации. Не редактируй её.
- **Профиль PowerShell** (`$PROFILE`, обычно
  `C:\Users\user\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`)
  содержит блок между `# >>> md-converters >>>` и `# <<< md-converters <<<`,
  где функции `tomd`/`pdf2md`/`html2md` указывают на `V:\md-converters`.

## Архитектура

- **`convert_to_md.py`** — единственный скрипт, вся логика. Раньше было два
  отдельных (`convert_pdf_to_md.py`, `convert_html_to_md.py`) — они УДАЛЕНЫ
  и слиты сюда.
- Команды-обёртки: `tomd` = весь функционал; `pdf2md` = `tomd --only pdf`;
  `html2md` = `tomd --only html,htm`. Различие только в фильтре формата при
  обходе папки/маски (одиночный явный файл конвертируется всегда).
- Точки входа для pip (console_scripts в `pyproject.toml`):
  `cli_tomd` / `cli_pdf` / `cli_html` в `convert_to_md.py`.
- Поле `generator` во front-matter выводится из набора расширений
  (`_tool_name`): `{.pdf}`→`pdf2md`, `{.html,.htm}`→`html2md`, иначе `tomd`.

## Файлы репозитория

| Файл | Назначение |
|------|------------|
| `convert_to_md.py` | основной скрипт (вся логика) |
| `install.ps1` | Windows-установщик: deps + команды в профиль + пункт Send To |
| `pyproject.toml` | pip-пакет, console_scripts (tomd/pdf2md/html2md) |
| `README.md` | инструкция (рус + краткая англ. секция) |
| `LICENSE` | MIT |
| `.github/workflows/ci.yml` | CI: смоук-тест на Python 3.11/3.12 |
| `examples/sample-report.html` + `.md` | пример вход/выход |
| `.gitignore` | игнор: `__pycache__`, build, `sendto-convert.cmd` и др. |

`sendto-convert.cmd` генерируется install.ps1 под конкретный ПК
(захардкоженный путь к python) и **в git не коммитится** (в `.gitignore`).

## Возможности / флаги

`-r` рекурсия (пропускает `node_modules/.git/.next/dist/build/venv/...`);
`-f`/`--force` перезапись (иначе существующие `.md` пропускаются);
`-o DIR` вывод в одну папку (разводит совпадения именами `(2)`);
`--only EXT[,EXT]` фильтр форматов при маске/папке;
`--keep-images` оставить base64-картинки (по умолчанию сворачиваются в
плейсхолдер `![...]()`); `--no-frontmatter` без YAML-шапки;
URL (`http(s)://`) — тянет страницу через `convert_url`.
Прочее: маски, папки, front-matter (title/source/converted/generator),
чистка вывода (`tidy`), сводка с перечнем ошибок, автоопределение кодировки
HTML (cp1251 и др.) через перекодировку во временный UTF-8.

## Окружение

- Python, на который указывают команды:
  `C:\Users\user\AppData\Local\Programs\Python\Python314\python.exe`.
  На машине есть и второй Python (`...\Local\Python\pythoncore-3.14-64\`) —
  install.ps1 выбрал первый (он на PATH). Зависимость: `markitdown[all]`.
- ОС: Windows 11. Оболочка: PowerShell 7 (pwsh). `$PROFILE` — для текущего
  хоста (PowerShell 7).

## Известные ограничения (не баги)

- **PDF-таблицы — best-effort.** В PDF нет структуры таблиц (только текст с
  координатами), поэтому таблица может выйти и Markdown-таблицей, и текстом.
  HTML/Word/Excel хранят структуру — там таблицы надёжны. Если нужно лучше
  для PDF — подключить `pdfplumber`/`camelot` точечно.
- **Word-таблицы:** MarkItDown даёт пустую верхнюю строку-заголовок, реальные
  заголовки уезжают в первую строку тела (данные не теряются).
- **Картинки:** base64 по умолчанию сворачиваются в плейсхолдер (решение
  пользователя — так и оставить).

## Подводные камни для агентов

- **Кириллица в имени `.lnk`:** `WScript.Shell.CreateShortcut` теряет
  кириллицу в ИМЕНИ файла (downconvert в ANSI → `?` → невалидное имя).
  Обход в install.ps1: создать ярлык с латинским именем, затем
  `Move-Item`/`Rename-Item` в кириллицу (это Unicode). Не «чини» обратно.
- **Длина строк в `convert_to_md.py`:** держи ≤ 79 символов — IDE-линтер
  ругается E501. Проверяй после правок.
- **`.ps1` без BOM:** дочерний `pwsh -File` читает как UTF-8 — кириллица ок;
  но профиль пишем с `utf8BOM`, чтобы читали и PowerShell 5.1, и 7.
- **Песочница** периодически блокирует `Remove-Item` с маской `\*` или
  подозрительными путями — используй `-LiteralPath` на конкретную папку.

## Как разрабатывать и проверять

1. Правки — в `V:\md-converters\convert_to_md.py` (и обёртки/README).
2. Проверка: компиляция `python -m py_compile convert_to_md.py`; длина строк
   ≤ 79; функциональный тест на реальных файлах во временной папке
   (`$env:TEMP`), результат смотреть, temp убирать.
3. Установщик идемпотентен — `install.ps1` можно гонять повторно (сам
   убирает старый блок профиля и пункт Send To, прописывает заново).
4. CI (GitHub Actions) на каждый push в `main` гоняет смоук-тест
   (HTML и CSV) на Python 3.11/3.12 — должен быть зелёным.

## Git-процесс

- Коммиты на русском, в конце строка:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Push/pull разрешены пользователем. Команды: `git -C "V:\md-converters"`.
- Перед завершением правок: `git add -A && commit && push`, убедиться, что
  `git status -sb` показывает `## main...origin/main` без расхождений.

## История (что уже сделано)

1. Утилита `pdf2md` (PDF→MD) и `html2md` (HTML→MD) на MarkItDown.
2. `html2md`: маски `*`, папки, рекурсия `-r`, защита от перезаписи `-f`,
   front-matter, чистка, сводка, автоопределение кодировки cp1251.
3. Комплект (kit) + `install.ps1` + README + примеры; перенос на любой ПК.
4. Репозиторий на GitHub (private), лицензия MIT; `pdf2md` доведён до уровня
   `html2md`.
5. **Текущее состояние:** слияние в универсальный `convert_to_md.py`
   (команда `tomd`), форматы Word/Excel/PowerPoint/CSV/URL и др., флаги
   `-o`/`--only`/`--keep-images`, пункт «Отправить → Конвертировать в
   Markdown», pip-пакет (`pyproject.toml`), CI (GitHub Actions). README с
   бейджами и англ. секцией.

Проект считается завершённым и рабочим. Следующее по желанию — извлечение
таблиц из PDF (см. ограничения) при появлении конкретной потребности.
