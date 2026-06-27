# -*- coding: utf-8 -*-
"""Universal document -> Markdown converter (powered by MarkItDown, Microsoft).

Detects the format by extension: PDF, HTML, Word (.docx), Excel (.xlsx),
PowerPoint (.pptx), CSV, JSON, XML, EPUB, Outlook (.msg), Jupyter (.ipynb),
RSS, and web pages by URL.

Usage:
    python convert_to_md.py                      — interactive mode.
    python convert_to_md.py file.docx [...]      — explicit files.
    python convert_to_md.py *                    — all documents in the folder.
    python convert_to_md.py C:\\reports -r        — folder and nested ones.
    python convert_to_md.py https://site/page    — web page by URL.

Flags:
    -r, --recursive    recurse into subfolders (node_modules/.git etc. are
                       skipped automatically).
    -f, --force        overwrite existing .md (by default they are skipped
                       to avoid clobbering manual edits).
    -o, --output DIR   write .md into this folder instead of next to source.
    --mirror, --preserve-tree
                       with -o, preserve the source folder tree under DIR.
    --only EXT[,EXT]   when a glob/folder is given, keep only these
                       extensions (e.g.: --only pdf  or  --only docx,xlsx).
    --pdf-tables MODE  auto (default) | off. PDF table extraction via
                       pdfplumber (geometry-aware). 'off' falls back to the
                       plain MarkItDown text path.
    --keep-images      do not touch images: keep base64 and PPTX phantom
                       image links (by default they are folded into a
                       compact placeholder).
    --unsafe-raw-markdown
                       do not sanitize potentially dangerous links/HTML in
                       the output Markdown (for trusted sources only).
    --allow-private-url
                       allow URLs pointing at localhost / private / link-local
                       addresses.
    --url-timeout SEC  URL fetch timeout (default 20).
    --max-url-mb MB    URL response size cap (default 50).
    --max-input-mb MB  local file size cap (default 100).
    --conversion-timeout SEC
                       per-file conversion timeout (default 120).
    --no-sandbox       convert local files in the main process.
    --no-frontmatter   do not add the YAML header (source/converted).

Output: same name with .md extension (next to the source or in -o folder).
With -o --mirror, relative subfolders are kept under the output folder. On
name collision a " (2)", " (3)" suffix is appended. The extension can be
omitted at the input. HTML encoding (UTF-8, cp1251, etc.) is detected
automatically.
"""

from __future__ import annotations

import glob
import argparse
import hashlib
import io
import ipaddress
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

# pypdfium2 используется только для подсчёта страниц в PDF-диагностике
# (image-only detection). Импортируем лениво внутри функции — при отсутствии
# библиотеки остальная функциональность продолжает работать.
try:
    import pypdfium2  # noqa: F401  (used in _pdf_page_count)
except ImportError:  # pragma: no cover — pypdfium2 is a runtime dep
    pypdfium2 = None  # type: ignore[assignment]

# pdfplumber извлекает таблицы PDF по геометрии (линии/края заливок) —
# штатный PDF-путь MarkItDown ищет таблицы по координатам слов и теряет
# структуру (колонки слипаются/рвутся). pdfplumber уже стоит как
# транзитивная зависимость markitdown[pdf]; объявлен и напрямую в
# pyproject. Импорт ленивый: без него PDF-таблицы просто не извлекаются,
# остальное работает.
try:
    import pdfplumber  # noqa: F401  (used in PDF table extraction)
except ImportError:  # pragma: no cover — pdfplumber is a runtime dep
    pdfplumber = None  # type: ignore[assignment]

# Windows-консоль бывает в cp1252/cp866/cp1251 — без reconfigure кириллица
# в наших сообщениях уезжает в «кракозябры». Делаем ДО всех импортов, чтобы
# даже предупреждения сторонних библиотек шли в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    _enc = _stream.encoding
    if _enc and _enc.lower() not in ("utf-8", "utf8"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass  # не-текстовые потоки в редких средах

# markitdown тянет pydub, а тот при импорте предупреждает, что нет
# ffmpeg — для конвертации документов он не нужен, глушим.
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg")

try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None


def _missing_markitdown() -> None:
    # Не [all]: на Python 3.14 pip из-за него молча откатывается на 0.0.2.
    print("markitdown is not installed. Install it with:")
    print('  pip install "markitdown[pdf,docx,pptx,xlsx,xls,outlook]"'
          '>=0.1.0,<1.0.0')
    sys.exit(1)

# Форматы, которые берём при обходе папки/маски (по одному явному файлу
# конвертируем что угодно — MarkItDown сам разберётся).
SUPPORTED_SUFFIXES = {
    ".pdf", ".html", ".htm", ".docx", ".xlsx", ".pptx",
    ".csv", ".json", ".xml", ".epub", ".msg", ".ipynb", ".rss",
}

_EXTENSION = re.compile(r"^[a-z0-9]+$")

# Папки, которые при рекурсии не имеют смысла — не заходим туда.
EXCLUDE_DIRS = {
    "node_modules", ".next", ".git", ".svn", ".hg",
    "__pycache__", ".venv", "venv", "dist", "build", ".idea",
}

# Встроенная картинка в виде data-URI: огромный base64 в Markdown.
# URI допускает парные скобки (бывают в SVG), но обрывается на первой
# непарной «)» — иначе жадный матч съедал бы соседнюю разметку
# (картинку-ссылку [![alt](data:...)](url), смежные картинки и т.п.).
_DATA_IMG = re.compile(
    r"!\[(?P<alt>[^\]]*)\]"
    r"\(data:image/[^()\s]*(?:\([^()\s]*\)[^()\s]*)*\)")

# Картинка из PPTX: MarkItDown пишет ![alt](ИмяФигуры.jpg), но сам файл
# из презентации не извлекает — ссылка всегда битая, и просмотрщики
# рисуют вместо неё ошибку (EntryNotFound / ENOENT).
_PHANTOM_IMG = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?!data:)[^)]*\)")

# Управляющие символы в тексте офисных форматов: PowerPoint хранит
# перенос строки внутри абзаца (<a:br/>) как vertical tab \x0b — в
# Markdown он виден «квадратиком». Меняем разделители строк на пробел,
# прочий невидимый мусор (C0, DEL, soft hyphen, ZWSP, BOM) убираем.
_CTRL_TO_SPACE = re.compile("[\x0b\x0c\x85\u2028\u2029]")
_CTRL_DROP = re.compile("[\x00-\x08\x0e-\x1f\x7f\xad\u200b\ufeff]")

_MD_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\n]*)\)")
_HTML_EVENT_ATTR = re.compile(
    r"\s+on[a-zA-Z0-9_-]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")
_HTML_URL_ATTR = re.compile(
    r"""(?ix)
    \s(?P<name>href|src|action|formaction)\s*=\s*
    (?P<quote>["']?)(?P<value>[^"'\s>]+)(?P=quote)
    """
)
_DANGEROUS_BLOCK_TAG = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|style)\b[^>]*>.*?"
    r"</\s*\1\s*>"
)
_DANGEROUS_SINGLE_TAG = re.compile(
    r"(?is)<\s*(script|iframe|object|embed|style|meta|link)\b[^>]*>"
)
_DANGEROUS_AUTOLINK = re.compile(
    r"(?i)<\s*(javascript|vbscript|file|data)\s*:[^>\n]*>")
_REMAINING_DANGEROUS_SCHEME = re.compile(
    r"(?i)\b(?:javascript|vbscript|file|data)\s*:[^\s)\]>]*")
_REMAINING_DANGEROUS_NO_DATA = re.compile(
    r"(?i)\b(?:javascript|vbscript|file)\s*:[^\s)\]>]*")
_DANGEROUS_SCHEMES = {"javascript", "vbscript", "file", "data"}
_SAFE_DATA_IMAGE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|gif|webp|bmp);base64,"
    r"(?:[A-Za-z0-9+/]{4})*"
    r"(?:[A-Za-z0-9+/]{4}|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{2}==)$",
    re.IGNORECASE,
)
_MAX_REDIRECTS = 5
_DEFAULT_URL_TIMEOUT = 20.0
_DEFAULT_MAX_URL_MB = 50.0
_DEFAULT_MAX_INPUT_MB = 100.0
_DEFAULT_CONVERSION_TIMEOUT = 120.0
_SOURCE_ID_HEX_LEN = 32
_LEGACY_SOURCE_ID_HEX_LEN = 16
_SOURCE_ID_RE = re.compile(r"^(?P<kind>[a-z]+):(?P<digest>[0-9a-f]+)$")
_HTML_META_CHARSET = re.compile(
    rb"(?is)<meta[^>]+charset\s*=\s*['\"]?\s*([a-zA-Z0-9._-]+)")
_HTML_HTTP_EQUIV_CHARSET = re.compile(
    rb"(?is)<meta[^>]+content\s*=\s*['\"][^'\"]*charset=([a-zA-Z0-9._-]+)")
_CYRILLIC_ENCODINGS = ("cp1251", "koi8-r", "cp866", "mac_cyrillic")

_converter = None
__version__ = "1.2.0"


def _md() -> MarkItDown:
    global _converter
    if MarkItDown is None:
        _missing_markitdown()
    if _converter is None:
        _converter = MarkItDown()
    return _converter


def _is_url(token) -> bool:
    if not isinstance(token, str):
        return False
    clean = token.strip().strip('"').strip("'")
    return bool(re.match(r"(?i)^https?://", clean))


def _suffix_set(spec: str) -> set[str]:
    """'pdf,docx' -> {'.pdf', '.docx'}."""
    result = set()
    for raw in spec.split(","):
        part = raw.strip().lower()
        if not part:
            continue
        if part.startswith("-"):
            raise ValueError(f"extension cannot start with '-': {raw}")
        if any(ch in part for ch in ("/", "\\", ":")):
            raise ValueError(f"extension contains a path separator: {raw}")
        if any(ord(ch) < 32 for ch in part):
            raise ValueError(f"extension contains a control character: {raw}")
        if part.startswith("*."):
            part = part[1:]
        if part.startswith("."):
            part = part[1:]
        if not _EXTENSION.fullmatch(part):
            raise ValueError(f"invalid extension: {raw}")
        result.add("." + part)
    return result


def _tool_name(restrict: set[str] | None) -> str:
    """Имя для поля generator во front-matter — по набору расширений."""
    if restrict == {".pdf"}:
        return "pdf2md"
    if restrict == {".html", ".htm"}:
        return "html2md"
    return "tomd"


# --------------------------------------------------------------------------
# Поиск файлов
# --------------------------------------------------------------------------

def _excluded(path: Path) -> bool:
    return any(part in EXCLUDE_DIRS for part in path.parts)


def scan_dir(root: Path, recursive: bool,
             suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in filenames:
                if Path(name).suffix.lower() in suffixes:
                    files.append(Path(dirpath) / name)
    else:
        for item in root.iterdir():
            if item.is_file() and item.suffix.lower() in suffixes:
                files.append(item)
    if not files:
        where = "subfolders" if recursive else "folder"
        print(f"[error] No matching files found in {where} {root}.")
    return sorted(files)


def _gather_glob(pattern: str, recursive: bool,
                 suffixes: set[str]) -> list[Path]:
    matches = [Path(p) for p in glob.glob(pattern, recursive=recursive)]
    files = [
        p for p in matches
        if p.is_file()
        and p.suffix.lower() in suffixes
        and not _excluded(p)
    ]
    if not files:  # маска без расширения — подставим каждое из suffixes
        for suffix in sorted(suffixes):
            for p in glob.glob(pattern + suffix, recursive=recursive):
                path = Path(p)
                if path.is_file() and not _excluded(path):
                    files.append(path)
    return sorted(set(files))


def collect(token: str, recursive: bool,
            suffixes: set[str]) -> list[Path]:
    """Раскрывает имя/папку/маску в список путей к файлам."""
    token = token.strip().strip('"').strip("'")
    if not token:
        return []

    path = Path(token)
    if path.is_dir():
        return scan_dir(path, recursive, suffixes)
    if path.is_file():  # литеральное имя важнее маски: бывают файлы с [
        return [path]

    if any(ch in token for ch in "*?["):
        pattern = token
        if recursive and "**" not in token:
            parent = path.parent
            if str(parent) in ("", "."):
                pattern = f"**/{path.name}"
            else:
                pattern = str(parent / "**" / path.name)
        files = _gather_glob(pattern, recursive or "**" in pattern, suffixes)
        if not files:
            print(f"[error] No matching files for pattern {token}.")
        return files

    # обычное имя: расширение можно не вводить
    if not path.exists() and path.suffix == "":
        for suffix in sorted(suffixes):
            candidate = Path(token + suffix)
            if candidate.exists():
                return [candidate]
    return [path]  # существование проверит конвертация


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve())).lower()


def _glob_root(token: str) -> Path:
    root_parts = []
    for part in Path(token).parts:
        if any(ch in part for ch in "*?["):
            break
        root_parts.append(part)
    if not root_parts:
        return Path.cwd()
    return Path(*root_parts)


def _mirror_root_for_token(token: str) -> Path:
    token = token.strip().strip('"').strip("'")
    path = Path(token)
    if path.is_dir():
        return path
    if path.is_file():
        return path.parent
    if any(ch in token for ch in "*?["):
        return _glob_root(token)
    if path.parent != Path("."):
        return path.parent
    return Path.cwd()


def _mirror_relative(path: Path, root: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return Path(path.name)


# --------------------------------------------------------------------------
# Сборка Markdown
# --------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def _source_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    digest = digest[:_SOURCE_ID_HEX_LEN]
    return f"{kind}:{digest}"


def _source_id_for_path(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return _source_id("path", normalized)


def _source_id_for_url(url: str) -> str:
    return _source_id("url", url.strip())


def _source_id_matches(existing: str | None, expected: str | None) -> bool:
    if not existing or not expected:
        return False
    if existing == expected:
        return True
    existing_match = _SOURCE_ID_RE.fullmatch(existing)
    expected_match = _SOURCE_ID_RE.fullmatch(expected)
    if not existing_match or not expected_match:
        return False
    if existing_match.group("kind") != expected_match.group("kind"):
        return False
    existing_digest = existing_match.group("digest")
    expected_digest = expected_match.group("digest")
    shorter, longer = sorted(
        (existing_digest, expected_digest),
        key=len,
    )
    return (
        len(shorter) >= _LEGACY_SOURCE_ID_HEX_LEN
        and len(shorter) < len(longer)
        and longer.startswith(shorter)
    )


def front_matter(source: str, title: str | None, tool: str,
                 source_path: str | None = None,
                 source_id: str | None = None,
                 pdf_text_layer: str | None = None,
                 pdf_tables: int | None = None) -> str:
    """Build YAML front-matter. pdf_text_layer — PDF-specific diagnostic:
    'present' (text-rich PDF) or 'absent' (image-only / scan, no text).
    pdf_tables — число таблиц, извлечённых через pdfplumber (PDF-путь).
    None — соответствующее поле не пишется (не-PDF форматы)."""
    lines = ["---"]
    if title:
        lines.append(f"title: {_yaml_str(title)}")
    lines.append(f"source: {_yaml_str(source)}")
    lines.append(f"source_name: {_yaml_str(source)}")
    if source_path:
        lines.append(f"source_path: {_yaml_str(source_path)}")
    if source_id:
        lines.append(f"source_id: {_yaml_str(source_id)}")
    if pdf_text_layer is not None:
        lines.append(f"pdf_text_layer: {pdf_text_layer}")
    if pdf_tables is not None:
        lines.append(f"pdf_tables: {pdf_tables}")
    lines.append(f"converted: {date.today().isoformat()}")
    lines.append(f"generator: {tool} {__version__} (MarkItDown)")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# PDF-диагностика: средняя плотность печатных символов на страницу.
# 20 символов/стр — нижний порог «какой-то осмысленный текст». Ниже —
# либо image-only / scan-only PDF, либо повреждённый файл. Подобрано
# эмпирически: типичный «пустой» PDF (скан без OCR) даёт 0-5 символов
# на страницу (пробелы и NUL); нормальный текстовый PDF — сотни.
_PDF_MIN_CHARS_PER_PAGE = 20


def _pdf_page_count(path: Path) -> int | None:
    """Число страниц в PDF, или None, если не удалось открыть (не PDF,
    битый файл, зашифрованный и т.п.). Использует pypdfium2."""
    if pypdfium2 is None:
        return None
    try:
        with pypdfium2.PdfDocument(str(path)) as doc:
            return len(doc)
    except Exception:
        return None


def _pdf_text_layer_diagnose(
    text: str, page_count: int | None
) -> str | None:
    """'present' | 'absent' | None (неизвестно).

    None возвращается, если:
    - не PDF (page_count is None) — диагностика не выполняется;
    - PDF без страниц — нет данных.
    Иначе сравнивает печатные символы в результате MarkItDown с порогом
    pages * _PDF_MIN_CHARS_PER_PAGE.
    """
    if not page_count:
        return None
    printable = sum(1 for ch in text if ch.isprintable() and not ch.isspace())
    threshold = page_count * _PDF_MIN_CHARS_PER_PAGE
    if printable < threshold:
        return "absent"
    return "present"


# --------------------------------------------------------------------------
# PDF-таблицы через pdfplumber (по геометрии, а не по координатам слов)
# --------------------------------------------------------------------------

# Сначала пробуем стратегию по линиям/краям заливок, затем по тексту
# (безбордюрные таблицы). Первая, давшая настоящие таблицы, — побеждает.
_PDF_TABLE_STRATEGIES = (
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    {"vertical_strategy": "text", "horizontal_strategy": "text"},
)
# Ячейка длиннее — это, скорее всего, проза, а не табличные данные.
_PDF_LONG_CELL = 60


class _PdfResult:
    """Лёгкая замена результата MarkItDown для PDF-пути с таблицами:
    тот же интерфейс (.text_content/.title), плюс число таблиц."""

    def __init__(self, text_content: str, pdf_tables: int) -> None:
        self.text_content = text_content
        self.title = None
        self.pdf_tables = pdf_tables


def _pdf_cell(value) -> str:
    if value is None:
        return ""
    return str(value).replace("\n", " ").strip()


def _row_populated(row) -> int:
    return sum(1 for c in row if c is not None and str(c).strip())


def _row_text(row) -> str:
    """Текст строки как ПРОЗА (для блоков-склеек, не GFM-ячеек):
    сохраняем внутренние переносы строк ячейки — иначе многострочный
    абзац/заголовок, попавший в таблицу одной ячейкой, схлопнется в
    «простыню» (регрессия)."""
    cells = [str(c).strip() for c in row
             if c is not None and str(c).strip()]
    return "\n".join(cells)


def _drop_empty_columns(rows: list) -> list:
    """Убирает столбцы, пустые во всех строках (артефакт безбордюрных
    таблиц, где заливка добавляет лишнюю колонку)."""
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    keep = [
        col for col in range(width)
        if any(col < len(r) and r[col] is not None
               and str(r[col]).strip() for r in rows)
    ]
    if len(keep) == width:
        return rows
    return [[r[c] if c < len(r) else None for c in keep] for r in rows]


def _looks_like_table(rows: list) -> bool:
    """Отсекает прозу, обёрнутую pdfplumber в «таблицу»: нужно ≥2 колонок,
    ≥2 строк с 2+ заполненными ячейками и не сплошной длинный текст."""
    if not rows or max(len(r) for r in rows) < 2:
        return False
    if sum(1 for r in rows if _row_populated(r) >= 2) < 2:
        return False
    cells = [str(c) for r in rows for c in r
             if c is not None and str(c).strip()]
    if not cells:
        return False
    longish = sum(1 for c in cells if len(c.strip()) > _PDF_LONG_CELL)
    return longish / len(cells) <= 0.5


def _segment_table_rows(rows: list) -> list:
    """Делит «сырые» строки на блоки по порядку чтения: ("table", rows)
    для строк с 2+ ячейками и ("text", str) для строк-склеек (заголовки
    над/под таблицей и между разделами, прилипшие из-за заливки)."""
    blocks: list = []
    current: list = []
    for row in rows:
        if _row_populated(row) >= 2:
            current.append(row)
            continue
        if current:
            blocks.append(("table", current))
            current = []
        text = _row_text(row)
        if text:
            blocks.append(("text", text))
    if current:
        blocks.append(("table", current))
    return blocks


def _table_to_gfm(rows: list) -> str:
    """Строки -> GitHub-flavored Markdown. Экранирует `|`, схлопывает
    переносы, дополняет рваные строки. Без pandas/tabulate — те не
    экранируют `|` и тянут лишние зависимости."""
    width = max(len(r) for r in rows)
    norm = []
    for row in rows:
        cells = [_pdf_cell(c).replace("|", "\\|") for c in row]
        cells += [""] * (width - len(cells))
        norm.append(cells)
    out = ["| " + " | ".join(norm[0]) + " |",
           "| " + " | ".join("---" for _ in norm[0]) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(out)


def _crop_text(page, top0: float, top1: float) -> str:
    """Текст полосы страницы [top0; top1) — то, что вне таблицы. Так
    содержимое таблицы не дублируется прозой."""
    if top1 - top0 < 2:
        return ""
    try:
        crop = page.crop((0, max(0, top0), page.width,
                          min(page.height, top1)))
        return (crop.extract_text() or "").strip()
    except Exception:
        return ""


def _page_blocks(page) -> list:
    """Упорядоченные блоки страницы: ("text", str) / ("table", rows).
    Если настоящих таблиц нет — весь текст страницы одним блоком."""
    regions = []
    for settings in _PDF_TABLE_STRATEGIES:
        try:
            found = page.find_tables(settings)
        except Exception:
            found = []
        for tbl in found:
            try:
                rows = tbl.extract()
            except Exception:
                continue
            has_table = any(
                _looks_like_table(_drop_empty_columns(block))
                for kind, block in _segment_table_rows(rows)
                if kind == "table"
            )
            if has_table:
                regions.append((tbl.bbox, rows))
        if regions:
            break

    if not regions:
        text = (page.extract_text() or "").strip()
        return [("text", text)] if text else []

    regions.sort(key=lambda r: r[0][1])
    blocks: list = []
    cursor = 0.0
    for bbox, rows in regions:
        top, bottom = bbox[1], bbox[3]
        if top < cursor - 1:  # перекрытие с уже обработанной таблицей
            continue
        above = _crop_text(page, cursor, top)
        if above:
            blocks.append(("text", above))
        for kind, block in _segment_table_rows(rows):
            if kind == "text":
                blocks.append(("text", block))
                continue
            block = _drop_empty_columns(block)
            if _looks_like_table(block):
                blocks.append(("table", block))
            else:
                joined = "\n".join(
                    _row_text(r) for r in block if _row_text(r)
                )
                if joined:
                    blocks.append(("text", joined))
        cursor = max(cursor, bottom)
    below = _crop_text(page, cursor, page.height)
    if below:
        blocks.append(("text", below))
    return blocks


def _join_continued_tables(blocks: list) -> list:
    """Склеивает таблицы, перенесённые на следующую страницу: соседние
    table-блоки с одинаковым числом колонок, где продолжение повторяет
    строку-заголовок (типично для экспорта из Word/PowerPoint)."""
    merged: list = []
    for kind, content in blocks:
        if kind == "table" and merged and merged[-1][0] == "table":
            prev = merged[-1][1]
            same_cols = (max(len(r) for r in prev) ==
                         max(len(r) for r in content))
            header_repeat = (
                same_cols and content and prev and
                [_pdf_cell(c) for c in content[0]] ==
                [_pdf_cell(c) for c in prev[0]]
            )
            if header_repeat:
                prev.extend(content[1:])
                continue
        merged.append((kind, list(content) if kind == "table" else content))
    return merged


def _pdf_tables_result(path: Path):
    """PDF -> _PdfResult с Markdown-таблицами, либо None (pdfplumber нет,
    документ без таблиц, или ничего не извлеклось — тогда вызывающий код
    откатывается на штатный путь MarkItDown)."""
    if pdfplumber is None:
        return None
    try:
        doc_blocks: list = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                doc_blocks.extend(_page_blocks(page))
                page.close()  # освобождаем кэш страницы сразу
    except Exception:
        return None
    if not any(kind == "table" for kind, _ in doc_blocks):
        return None  # таблиц нет — пусть отработает обычный путь
    doc_blocks = _join_continued_tables(doc_blocks)
    parts = []
    table_count = 0
    for kind, content in doc_blocks:
        if kind == "table":
            parts.append(_table_to_gfm(content))
            table_count += 1
        elif content:
            parts.append(content)
    text = "\n\n".join(p for p in parts if p).strip()
    if not text:
        return None
    return _PdfResult(text + "\n", table_count)


def _img_placeholder(match: re.Match) -> str:
    alt = _markdown_label(match.group("alt") or "embedded image")
    return f"![{alt}]()"


def _markdown_label(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = value.replace("\\", "\\\\")
    value = value.replace("[", "\\[").replace("]", "\\]")
    return value


def _normalized_scheme(value: str) -> str | None:
    clean = value.strip().strip("<>").strip()
    clean = re.sub(r"[\x00-\x20]+", "", clean)
    decoded = unquote(clean)
    decoded = re.sub(r"[\x00-\x20]+", "", decoded)
    if ":" not in decoded:
        return None
    scheme = decoded.split(":", 1)[0].lower()
    if re.fullmatch(r"[a-z][a-z0-9+.-]*", scheme):
        return scheme
    return None


def _safe_markdown_target(value: str, allow_data_images: bool) -> str:
    value = value.strip()
    scheme = _normalized_scheme(value)
    if scheme is None:
        return value
    if scheme == "data" and allow_data_images:
        return value if _SAFE_DATA_IMAGE.fullmatch(value.strip()) else ""
    if scheme in _DANGEROUS_SCHEMES:
        return ""
    return value


def _sanitize_markdown_link(match: re.Match,
                            keep_images: bool) -> str:
    marker, label, target = match.groups()
    safe_target = _safe_markdown_target(
        target,
        allow_data_images=bool(marker) and keep_images,
    )
    return f"{marker}[{_markdown_label(label)}]({safe_target})"


def _sanitize_html_url_attr(match: re.Match,
                            keep_images: bool) -> str:
    value = match.group("value")
    safe = _safe_markdown_target(value, allow_data_images=keep_images)
    if not safe:
        safe = "#"
    quote = match.group("quote") or '"'
    return f' {match.group("name").lower()}={quote}{safe}{quote}'


def sanitize_markdown(text: str, keep_images: bool) -> str:
    """Нейтрализует опасные ссылки и raw HTML в Markdown-теле."""
    text = _DANGEROUS_BLOCK_TAG.sub("", text)
    text = _DANGEROUS_SINGLE_TAG.sub("", text)
    text = _HTML_EVENT_ATTR.sub("", text)
    text = _HTML_URL_ATTR.sub(
        lambda m: _sanitize_html_url_attr(m, keep_images),
        text,
    )
    text = _DANGEROUS_AUTOLINK.sub("<blocked>", text)
    text = _MD_LINK.sub(
        lambda m: _sanitize_markdown_link(m, keep_images),
        text,
    )
    if keep_images:
        return _REMAINING_DANGEROUS_NO_DATA.sub("blocked", text)
    return _REMAINING_DANGEROUS_SCHEME.sub("blocked", text)


# Псевдографика таблиц (box-drawing, U+2500..U+257F). Такие таблицы рисуют
# символами рамок прямо в тексте (часто — генераторы/ИИ); геометрии у них
# нет, поэтому pdfplumber их не видит, а в Markdown-вьюере они разъезжаются.
# Конвертируем их в GFM на этапе tidy (для любого формата; срабатывает
# только при наличии вертикалей псевдографики — на прозу не влияет).
_BOX_DRAW_CHARS = set(
    "─━│┃┄┅┆┇┈┉┊┋╌╍╎╏"
    "┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫"
    "┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋"
    "═║╔╦╗╠╬╣╚╩╝╒╓╕╖╗╘╙╛╜╞╟╡╢╤╥╧╨╪╫"
)
_BOX_VERTICAL = "│┃"


def _is_box_row(line: str) -> bool:
    return any(ch in line for ch in _BOX_VERTICAL)


def _is_box_border(line: str) -> bool:
    s = line.strip()
    return bool(s) and all(ch in _BOX_DRAW_CHARS or ch.isspace() for ch in s)


def _box_block_to_gfm(block: list) -> str | None:
    """Блок строк псевдографики -> GFM-таблица или None (если непохоже)."""
    rows = []
    for line in block:
        if not _is_box_row(line):
            continue  # строка-граница — пропускаем
        parts = re.split(r"[│┃]", line)
        # срезаем по одной пустой ячейке с краёв (от внешних рамок),
        # внутренние пустые ячейки сохраняем (позиции колонок важны)
        if parts and parts[0].strip() == "":
            parts = parts[1:]
        if parts and parts[-1].strip() == "":
            parts = parts[:-1]
        cells = [p.strip() for p in parts]
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return None
    width = max(len(r) for r in rows)
    if width < 2:
        return None
    rows = [r + [""] * (width - len(r)) for r in rows]
    # строки-продолжения (пустая первая ячейка) сливаем в предыдущую
    merged = [rows[0]]
    for r in rows[1:]:
        if r[0] == "" and any(r):
            prev = merged[-1]
            for k in range(width):
                if r[k]:
                    prev[k] = (prev[k] + " " + r[k]).strip()
        else:
            merged.append(r)
    if len(merged) < 2:
        merged = rows  # после слияния осталась одна шапка — без слияния

    def esc(cell: str) -> str:
        return cell.replace("|", "\\|")
    out = ["| " + " | ".join(esc(c) for c in merged[0]) + " |",
           "| " + " | ".join("---" for _ in merged[0]) + " |"]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in merged[1:]]
    return "\n".join(out)


def _convert_box_tables(text: str) -> str:
    """Заменяет блоки псевдографики таблиц на GFM. Быстрый выход, если
    вертикалей псевдографики нет (на обычный текст и GFM с ASCII `|` не
    влияет — ищем только `│`/`┃`)."""
    if not any(ch in text for ch in _BOX_VERTICAL):
        return text
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if _is_box_row(lines[i]) or _is_box_border(lines[i]):
            j = i
            block = []
            while j < n and (_is_box_row(lines[j])
                             or _is_box_border(lines[j])):
                block.append(lines[j])
                j += 1
            gfm = _box_block_to_gfm(block)
            if gfm and any(_is_box_row(b) for b in block):
                out.append(gfm)
            else:
                out.extend(block)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def tidy(text: str, keep_images: bool, phantom_images: bool = False,
         safe_markdown: bool = True) -> str:
    """Прибирает вывод: чистит управляющие символы, конвертирует
    псевдографику таблиц в GFM, убирает хвостовые пробелы, схлопывает
    пустые строки, обрезает края и (по умолчанию) сворачивает base64-
    картинки и битые картинки-заглушки из PPTX."""
    text = _CTRL_TO_SPACE.sub(" ", text)
    text = _CTRL_DROP.sub("", text)
    text = _convert_box_tables(text)
    if not keep_images:
        text = _DATA_IMG.sub(_img_placeholder, text)
        if phantom_images:
            text = _PHANTOM_IMG.sub(_img_placeholder, text)
    if safe_markdown:
        text = sanitize_markdown(text, keep_images)
    out: list[str] = []
    blank = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        if line == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(line)
            blank = False
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _yaml_unquote(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    return value


def _existing_frontmatter(target: Path) -> dict[str, str]:
    """Простое чтение YAML front-matter, который пишет эта утилита."""
    try:
        with target.open(encoding="utf-8") as fh:
            first = fh.readline()
            if first.strip() != "---":
                return {}
            values = {}
            for line in fh:
                if line.strip() == "---":
                    break
                key, sep, value = line.partition(":")
                if sep:
                    values[key.strip()] = _yaml_unquote(value.strip())
            return values
    except OSError:
        return {}


def _existing_source(target: Path) -> str | None:
    """Значение source из front-matter готового .md (или None)."""
    return _existing_frontmatter(target).get("source")


def _existing_source_id(target: Path) -> str | None:
    """Значение source_id из front-matter готового .md (или None)."""
    return _existing_frontmatter(target).get("source_id")


def _plan_target(stem: str, dest_dir: Path, planned: set[str],
                 source: str | None = None,
                 source_id: str | None = None,
                 allow_legacy_source_match: bool = False) -> Path:
    """Путь к .md; совпадения имён (report.docx и report.pdf рядом)
    разводит суффиксами (2), (3)..., чтобы не затирать друг друга.
    Сверяет и план текущего запуска, и source в уже лежащих на диске
    .md — чтобы повторный прогон части файлов попал в «свои» цели."""
    target = dest_dir / (stem + ".md")
    n = 2
    while True:
        if str(target).lower() not in planned:
            if not target.exists():
                break
            existing_id = _existing_source_id(target)
            if _source_id_matches(existing_id, source_id):
                break  # наш же файл (или сверять нечего) — берём
            src = _existing_source(target)
            if (not source_id and source and src == source):
                break
            if allow_legacy_source_match and source and src == source:
                break
        target = dest_dir / f"{stem} ({n}).md"
        n += 1
    planned.add(str(target).lower())
    return target


def _plan_file_target(path: Path, opts: dict,
                      planned: set[str]) -> tuple[Path, str]:
    source_id = _source_id_for_path(path)
    dest_dir = opts.get("out_dir") or path.parent
    if opts.get("out_dir") and opts.get("mirror"):
        roots = opts.get("mirror_roots", {})
        root = roots.get(_path_key(path))
        if root is not None:
            dest_dir = opts["out_dir"] / _mirror_relative(path, root).parent
    target = _plan_target(
        path.stem,
        dest_dir,
        planned,
        path.name,
        source_id,
        allow_legacy_source_match=opts.get("out_dir") is None,
    )
    return target, source_id


def _plan_url_target(url: str, opts: dict,
                     planned: set[str]) -> tuple[Path, str]:
    source_id = _source_id_for_url(url)
    target = _plan_target(
        _url_stem(url),
        opts["out_dir"] or Path.cwd(),
        planned,
        url,
        source_id,
        allow_legacy_source_match=True,
    )
    return target, source_id


def _emit(target: Path, result, source: str, frontmatter: bool,
          keep_images: bool, tool: str, note: str | None,
          phantom_images: bool = False,
          source_path: str | None = None,
          source_id: str | None = None,
          safe_markdown: bool = True,
          pdf_text_layer: str | None = None) -> None:
    text = tidy(
        result.text_content,
        keep_images,
        phantom_images,
        safe_markdown=safe_markdown,
    )
    if frontmatter:
        title = getattr(result, "title", None)
        text = front_matter(
            source, title, tool, source_path, source_id,
            pdf_text_layer=pdf_text_layer,
            pdf_tables=getattr(result, "pdf_tables", None),
        ) + text
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    extra = f" ({note})" if note else ""
    print(f"Done: {target}{extra}")


# --------------------------------------------------------------------------
# Конвертация
# --------------------------------------------------------------------------

def _decode_with(raw: bytes, encoding: str) -> str | None:
    try:
        return raw.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return None


def _meta_charset(raw: bytes) -> str | None:
    head = raw[:4096]
    for pattern in (_HTML_META_CHARSET, _HTML_HTTP_EQUIV_CHARSET):
        match = pattern.search(head)
        if match:
            try:
                return match.group(1).decode("ascii").lower()
            except UnicodeDecodeError:
                return None
    return None


def _cyrillic_score(text: str) -> int:
    letters = [ch for ch in text if "\u0400" <= ch <= "\u04ff"]
    cyrillic = len(letters)
    lowercase = sum(1 for ch in letters if ch.islower())
    uppercase = sum(1 for ch in letters if ch.isupper())
    non_russian = sum(
        1 for ch in letters
        if not ("а" <= ch.lower() <= "я" or ch.lower() == "ё")
    )
    replacement = text.count("\ufffd")
    score = cyrillic * 2 + lowercase - uppercase
    score -= non_russian * 5 + replacement * 10
    return score


def _best_cyrillic_decode(raw: bytes) -> tuple[str, str] | None:
    candidates: list[tuple[int, str, str]] = []
    for encoding in _CYRILLIC_ENCODINGS:
        text = _decode_with(raw, encoding)
        if text is not None:
            candidates.append((_cyrillic_score(text), encoding, text))
    if not candidates:
        return None
    score, encoding, text = max(candidates, key=lambda item: item[0])
    if score > 0:
        return text, encoding
    return None


def decode_html_bytes(raw: bytes) -> tuple[str, str]:
    """Декодирует HTML с приоритетом BOM/meta и русскоязычных кодировок."""
    if raw.startswith(b"\xef\xbb\xbf"):
        text = _decode_with(raw, "utf-8-sig")
        if text is not None:
            return text, "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = _decode_with(raw, "utf-16")
        if text is not None:
            return text, "utf-16"

    declared = _meta_charset(raw)
    if declared:
        text = _decode_with(raw, declared)
        if text is not None:
            return text, declared

    cyrillic = _best_cyrillic_decode(raw)
    if cyrillic is not None:
        return cyrillic

    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
    except Exception:
        best = None
    if best is not None:
        return str(best), best.encoding

    return raw.decode("cp1251", errors="replace"), "cp1251-replace"


def _convert_reencoded(raw: bytes) -> tuple:
    """HTML не в UTF-8: определяем кодировку и гоним через UTF-8 temp."""
    text, enc = decode_html_bytes(raw)
    fd, tmp = tempfile.mkstemp(suffix=".html")
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)  # иначе при ошибке записи утёк бы дескриптор
    try:
        result = _md().convert(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return result, f"re-encoded from {enc}"


def _convert_file_data(path: Path) -> tuple:
    """(result, note). Для HTML — с автоопределением кодировки."""
    if path.suffix.lower() in (".html", ".htm"):
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return _convert_reencoded(raw)
    return _md().convert(str(path)), None


def _positive_float(value: str, name: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if number <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return number


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


def _resolved_ips(hostname: str) -> set[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"failed to resolve host {hostname!r}") from exc
    return {info[4][0] for info in infos}


def _check_url_allowed(url: str, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    if not parsed.hostname:
        raise ValueError("URL must contain a hostname")
    if allow_private:
        return
    blocked = [ip for ip in _resolved_ips(parsed.hostname)
               if not _is_public_ip(ip)]
    if blocked:
        sample = ", ".join(sorted(blocked)[:3])
        raise ValueError(
            f"URL points to a non-public address ({sample}); "
            "use --allow-private-url only for trusted local scenarios"
        )


def _read_limited_response(response, max_bytes: int) -> bytes:
    header = response.headers.get("content-length")
    if header:
        try:
            declared = int(header)
        except ValueError:
            declared = None
        if declared is not None and declared > max_bytes:
            raise ValueError(
                f"URL response exceeds the limit "
                f"({declared} bytes > {max_bytes})"
            )

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(
                f"URL response exceeds the limit "
                f"({max_bytes} bytes)"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _download_url(url: str, timeout: float, max_bytes: int,
                  allow_private: bool) -> tuple[bytes, str, str | None]:
    try:
        import requests
    except ImportError as exc:
        raise ValueError("URL mode requires the 'requests' package") from exc

    current = url.strip()
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Accept": "text/markdown, text/html;q=0.9, "
                  "text/plain;q=0.8, */*;q=0.1",
        "User-Agent": f"md-converters/{__version__}",
    })
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            _check_url_allowed(current, allow_private)
            response = session.get(
                current,
                allow_redirects=False,
                stream=True,
                timeout=(timeout, timeout),
            )
            try:
                if 300 <= response.status_code < 400:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("redirect without a Location header")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                final_url = response.url or current
                _check_url_allowed(final_url, allow_private)
                data = _read_limited_response(response, max_bytes)
                suffix = Path(urlparse(final_url).path).suffix or None
                return data, final_url, suffix
            finally:
                response.close()
        raise ValueError("too many redirects")
    finally:
        session.close()


def _convert_url_data(url: str, opts: dict) -> tuple:
    data, final_url, suffix = _download_url(
        url,
        timeout=opts["url_timeout"],
        max_bytes=opts["max_url_bytes"],
        allow_private=opts["allow_private_url"],
    )
    result = _md().convert_stream(
        io.BytesIO(data),
        file_extension=suffix,
        url=final_url,
    )
    return result, final_url


def _file_too_large(path: Path, max_bytes: int) -> bool:
    try:
        return path.stat().st_size > max_bytes
    except OSError:
        return False


def _convert_file_to_target(path: Path, target: Path, opts: dict,
                            suffix: str, source_id: str) -> str:
    print(f"Converting {path.name} ...")
    result = None
    note = None
    # PDF: сначала пытаемся извлечь таблицы по геометрии (pdfplumber).
    # Если документ без таблиц или pdfplumber недоступен — откат на
    # штатный путь MarkItDown ниже (поведение не меняется).
    if suffix == ".pdf" and opts.get("pdf_tables", "auto") != "off":
        try:
            pdf_result = _pdf_tables_result(path)
        except Exception:
            pdf_result = None
        if pdf_result is not None:
            result = pdf_result
            note = f"{pdf_result.pdf_tables} table(s) via pdfplumber"
    if result is None:
        try:
            result, note = _convert_file_data(path)
        except Exception as exc:
            print(f"[error] Failed to convert {path.name}: {exc}")
            return "fail"

    # PDF-специфичная диагностика: image-only / scan-only PDF.
    # Если у PDF нет текстового слоя — MarkItDown вернёт пустой/мусорный
    # Markdown, и пользователь должен знать, почему.
    pdf_text_layer = None
    if suffix == ".pdf":
        page_count = _pdf_page_count(path)
        if page_count is not None:
            pdf_text_layer = _pdf_text_layer_diagnose(
                result.text_content, page_count
            )
            if pdf_text_layer == "absent":
                print(
                    f"[warning] {path.name}: PDF without a text layer "
                    f"(only images / scan, {page_count} page(s)). "
                    f"Open in ABBYY FineReader or run "
                    f"`ocrmypdf {path.name} {path.stem}-ocr.pdf` "
                    f"(requires Tesseract).",
                    file=sys.stderr,
                )

    try:
        _emit(target, result, path.name, opts["frontmatter"],
              opts["keep_images"], opts["tool"], note,
              phantom_images=(suffix == ".pptx"),
              source_path=str(path), source_id=source_id,
              safe_markdown=not opts.get("unsafe_raw_markdown", False),
              pdf_text_layer=pdf_text_layer)
    except OSError as exc:
        print(f"[error] Failed to write {target.name}: {exc}")
        return "fail"
    return "ok"


def _worker_payload(opts: dict) -> str:
    payload = {
        "frontmatter": opts["frontmatter"],
        "keep_images": opts["keep_images"],
        "unsafe_raw_markdown": opts.get("unsafe_raw_markdown", False),
        "tool": opts["tool"],
        "pdf_tables": opts.get("pdf_tables", "auto"),
    }
    return json.dumps(payload, ensure_ascii=False)


def _convert_file_subprocess(path: Path, target: Path, opts: dict,
                             suffix: str, source_id: str) -> str:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--_worker-convert",
        str(path),
        str(target),
        suffix,
        source_id,
        _worker_payload(opts),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=opts["conversion_timeout"],
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[error] Conversion timeout for {path.name} "
            f"({opts['conversion_timeout']} sec)"
        )
        return "fail"
    except UnicodeDecodeError as exc:
        print(
            f"[error] Worker for {path.name} produced non-UTF-8 "
            f"output: {exc}"
        )
        return "fail"
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return "ok" if completed.returncode == 0 else "fail"


def _worker_convert(argv: list[str]) -> int:
    if len(argv) != 5:
        print("[error] Invalid internal worker invocation")
        return 2
    path = Path(argv[0])
    target = Path(argv[1])
    suffix = argv[2]
    source_id = argv[3]
    try:
        worker_opts = json.loads(argv[4])
    except json.JSONDecodeError as exc:
        print(f"[error] Invalid worker options: {exc}")
        return 2
    status = _convert_file_to_target(path, target, worker_opts,
                                     suffix, source_id)
    return 0 if status == "ok" else 1


def convert_file(path: Path, opts: dict) -> str:
    if not path.exists():
        print(f"[error] File not found: {path.resolve()}")
        return "fail"
    suffix = path.suffix.lower()
    if suffix not in opts["scan"]:
        print(f"[warning] {path.name} — format not in the filter list, "
              "trying anyway.")

    target, source_id = _plan_file_target(path, opts, opts["planned"])
    if target.exists() and not opts["force"]:
        print(f"[skip] {target.name} already exists "
              "(use -f / --force to overwrite)")
        return "skip"

    max_bytes = opts.get("max_input_bytes", 0)
    if max_bytes > 0 and _file_too_large(path, max_bytes):
        print(
            f"[error] {path.name} exceeds the size limit "
            f"({opts['max_input_mb']} MB)"
        )
        return "fail"

    if opts.get("sandbox", False):
        return _convert_file_subprocess(path, target, opts, suffix, source_id)
    return _convert_file_to_target(path, target, opts, suffix, source_id)


def _url_stem(url: str) -> str:
    parsed = urlparse(url)
    name = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    name = re.sub(r"[^\w.-]+", "-", name).strip("-")
    stem = Path(name).stem
    return stem or parsed.netloc.replace(".", "-") or "page"


def convert_url(url: str, opts: dict) -> str:
    target, source_id = _plan_url_target(url, opts, opts["planned"])
    if target.exists() and not opts["force"]:
        print(f"[skip] {target.name} already exists "
              "(use -f / --force to overwrite)")
        return "skip"
    print(f"Downloading {url} ...")
    try:
        result, final_url = _convert_url_data(url, opts)
    except Exception as exc:
        print(f"[error] Failed to download {url}: {exc}")
        return "fail"
    try:
        _emit(target, result, url, opts["frontmatter"],
              opts["keep_images"], opts["tool"], None,
              source_path=final_url, source_id=source_id,
              safe_markdown=not opts.get("unsafe_raw_markdown", False))
    except OSError as exc:
        print(f"[error] Failed to write {target.name}: {exc}")
        return "fail"
    return "ok"


def run(items: list, opts: dict) -> list:
    ok = skipped = 0
    failed = []
    for item in items:
        if _is_url(item):
            status = convert_url(item, opts)
        else:
            status = convert_file(item, opts)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skipped += 1
        else:
            failed.append(item)

    if len(items) > 1:
        parts = [f"converted {ok} of {len(items)}"]
        if skipped:
            parts.append(f"skipped {skipped}")
        if failed:
            parts.append(f"failed {len(failed)}")
        print("Total: " + ", ".join(parts) + ".")
        if failed:
            print("Failed to process:")
            for item in failed:
                print(f"  - {item}")
    return failed


# --------------------------------------------------------------------------
# Разбор аргументов / режимы
# --------------------------------------------------------------------------

class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parse(tokens: list) -> dict:
    errors: list[str] = []
    parser = _ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument("-f", "--force", action="store_true")
    parser.add_argument("-r", "--recursive", action="store_true")
    parser.add_argument("--no-frontmatter", dest="frontmatter",
                        action="store_false", default=True)
    parser.add_argument("--keep-images", action="store_true")
    parser.add_argument("--unsafe-raw-markdown", action="store_true")
    parser.add_argument("--allow-private-url", action="store_true")
    parser.add_argument("--url-timeout",
                        default=str(_DEFAULT_URL_TIMEOUT))
    parser.add_argument("--max-url-mb",
                        default=str(_DEFAULT_MAX_URL_MB))
    parser.add_argument("--max-input-mb",
                        default=str(_DEFAULT_MAX_INPUT_MB))
    parser.add_argument("--conversion-timeout",
                        default=str(_DEFAULT_CONVERSION_TIMEOUT))
    parser.add_argument("--no-sandbox", dest="sandbox",
                        action="store_false", default=True)
    parser.add_argument("-o", "--output", dest="out_dir")
    parser.add_argument("--mirror", "--preserve-tree", dest="mirror",
                        action="store_true")
    parser.add_argument("--only")
    parser.add_argument("--pdf-tables", dest="pdf_tables", default="auto")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("patterns", nargs="*")
    try:
        parsed = parser.parse_args(tokens)
    except ValueError as exc:
        errors.append(f"[error] Invalid arguments: {exc}")
        parsed = parser.parse_args([])

    if parsed.help:
        print(__doc__)
        sys.exit(0)
    if parsed.version:
        print(f"md-converters {__version__}")
        sys.exit(0)

    out_dir = None
    if parsed.out_dir is not None:
        val = parsed.out_dir.strip().strip('"').strip("'")
        if val and not val.startswith("-"):
            out_dir = Path(val)
        else:
            errors.append("[error] -o/--output requires a folder path.")
    if parsed.mirror and out_dir is None:
        errors.append("[error] --mirror/--preserve-tree requires -o/--output.")

    only = None
    if parsed.only is not None:
        spec = parsed.only.strip().strip('"').strip("'")
        if not spec or spec.startswith("-"):
            errors.append("[error] --only requires extensions, "
                          "e.g.: --only pdf,docx.")
        else:
            try:
                only = _suffix_set(spec) or None
            except ValueError as exc:
                errors.append(f"[error] Invalid --only: {exc}")
            if only is None and not errors:
                errors.append("[error] --only requires extensions, "
                              "e.g.: --only pdf,docx.")
    try:
        url_timeout = _positive_float(parsed.url_timeout, "--url-timeout")
    except ValueError as exc:
        errors.append(f"[error] {exc}")
        url_timeout = _DEFAULT_URL_TIMEOUT

    try:
        max_url_mb = _positive_float(parsed.max_url_mb, "--max-url-mb")
    except ValueError as exc:
        errors.append(f"[error] {exc}")
        max_url_mb = _DEFAULT_MAX_URL_MB

    try:
        max_input_mb = _positive_float(parsed.max_input_mb, "--max-input-mb")
    except ValueError as exc:
        errors.append(f"[error] {exc}")
        max_input_mb = _DEFAULT_MAX_INPUT_MB

    try:
        conversion_timeout = _positive_float(
            parsed.conversion_timeout,
            "--conversion-timeout",
        )
    except ValueError as exc:
        errors.append(f"[error] {exc}")
        conversion_timeout = _DEFAULT_CONVERSION_TIMEOUT

    pdf_tables = (parsed.pdf_tables or "auto").strip().strip('"').strip("'")
    pdf_tables = pdf_tables.lower()
    if pdf_tables not in ("auto", "off"):
        errors.append("[error] --pdf-tables requires auto or off.")
        pdf_tables = "auto"

    return {
        "patterns": parsed.patterns, "force": parsed.force,
        "recursive": parsed.recursive, "frontmatter": parsed.frontmatter,
        "keep_images": parsed.keep_images,
        "unsafe_raw_markdown": parsed.unsafe_raw_markdown,
        "allow_private_url": parsed.allow_private_url,
        "url_timeout": url_timeout,
        "max_url_mb": max_url_mb,
        "max_input_mb": max_input_mb,
        "conversion_timeout": conversion_timeout,
        "sandbox": parsed.sandbox,
        "out_dir": out_dir, "mirror": parsed.mirror,
        "only": only, "pdf_tables": pdf_tables, "errors": errors,
    }


def _build_opts(parsed: dict, default_only: list | None) -> dict:
    only = parsed["only"]
    if only is None and default_only:
        only = _suffix_set(",".join(default_only))
    scan = only or SUPPORTED_SUFFIXES
    return {
        "force": parsed["force"],
        "frontmatter": parsed["frontmatter"],
        "keep_images": parsed["keep_images"],
        "unsafe_raw_markdown": parsed["unsafe_raw_markdown"],
        "allow_private_url": parsed["allow_private_url"],
        "url_timeout": parsed["url_timeout"],
        "max_url_bytes": int(parsed["max_url_mb"] * 1024 * 1024),
        "max_input_mb": parsed["max_input_mb"],
        "max_input_bytes": int(parsed["max_input_mb"] * 1024 * 1024),
        "conversion_timeout": parsed["conversion_timeout"],
        "sandbox": parsed["sandbox"],
        "out_dir": parsed["out_dir"],
        "mirror": parsed["mirror"],
        "mirror_roots": {},
        "scan": scan,
        "pdf_tables": parsed.get("pdf_tables", "auto"),
        "tool": _tool_name(only),
        "planned": set(),
    }


def _items_from(patterns: list, recursive: bool, scan: set,
                opts: dict | None = None) -> list:
    items = []
    seen = set()
    for pattern in patterns:
        if _is_url(pattern):
            items.append(pattern.strip().strip('"').strip("'"))
            continue
        mirror_root = _mirror_root_for_token(pattern)
        for path in collect(pattern, recursive, scan):
            key = _path_key(path)
            if key not in seen:
                seen.add(key)
                items.append(path)
                if opts and opts.get("mirror"):
                    opts["mirror_roots"][key] = mirror_root
    return items


def interactive(default_only: list | None) -> None:
    print("=== Universal converter -> Markdown ===")
    print("Enter a file, folder, glob, or URL and press Enter.")
    print("Formats: PDF, HTML, Word, Excel, PowerPoint, CSV, etc.")
    print("Examples:  *   |   C:\\reports -r   |   https://site/page")
    print("Empty line or Ctrl+C to exit.")
    while True:
        try:
            line = input("\nFile> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            break

        # shlex с posix=False уважает кавычки (пути с пробелами при
        # перетаскивании файла) и не трогает обратные слэши Windows.
        try:
            tokens = shlex.split(line, posix=False)
        except ValueError:
            tokens = line.split()
        parsed = _parse(tokens)
        if parsed["errors"]:
            for msg in parsed["errors"]:
                print(msg)
            continue
        opts = _build_opts(parsed, default_only)
        items = _items_from(parsed["patterns"], parsed["recursive"],
                            opts["scan"], opts)
        if not items:
            continue

        force = parsed["force"]
        if not force:
            # Предсказываем цели той же логикой, что и сам прогон
            # (черновой planned), иначе вопрос не совпадёт с делом.
            sim: set[str] = set()
            existing = []
            for it in items:
                if _is_url(it):
                    _plan_url_target(it, opts, sim)
                    continue
                t, _ = _plan_file_target(it, opts, sim)
                if t.exists():
                    existing.append(it)
            if existing:
                answer = input(
                    f"{len(existing)} file(s) already have a .md. "
                    "Overwrite? (y = yes / Enter = skip): "
                )
                force = answer.strip().lower() in ("y", "yes", "д", "да")
        opts["force"] = force
        run(items, opts)


def _main(argv: list, default_only: list | None = None) -> int:
    if argv and argv[0] == "--_worker-convert":
        return _worker_convert(argv[1:])
    parsed = _parse(argv)
    if parsed["errors"]:
        for msg in parsed["errors"]:
            print(msg)
        return 2
    if parsed["patterns"]:
        opts = _build_opts(parsed, default_only)
        items = _items_from(parsed["patterns"], parsed["recursive"],
                            opts["scan"], opts)
        failed = run(items, opts)
        return 1 if (failed or not items) else 0
    interactive(default_only)
    return 0


# Точки входа для pip (console_scripts) и прямого запуска.
def cli_tomd() -> int:
    return _main(sys.argv[1:], default_only=None)


def cli_pdf() -> int:
    return _main(sys.argv[1:], default_only=["pdf"])


def cli_html() -> int:
    return _main(sys.argv[1:], default_only=["html", "htm"])


if __name__ == "__main__":
    sys.exit(cli_tomd())
