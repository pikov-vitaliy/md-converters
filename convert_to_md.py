# -*- coding: utf-8 -*-
"""Универсальная конвертация документов в Markdown (MarkItDown, Microsoft).

Понимает формат по расширению: PDF, HTML, Word (.docx), Excel (.xlsx),
PowerPoint (.pptx), CSV, JSON, XML, EPUB, Outlook (.msg), Jupyter (.ipynb),
RSS, а также веб-страницы по URL.

Использование:
    python convert_to_md.py                      — интерактивный режим.
    python convert_to_md.py file.docx [...]      — конкретные файлы.
    python convert_to_md.py *                    — все документы в папке.
    python convert_to_md.py C:\\reports -r        — папка и вложенные.
    python convert_to_md.py https://site/page    — веб-страница по URL.

Флаги:
    -r, --recursive    обходить вложенные папки (node_modules/.git и т.п.
                       пропускаются автоматически).
    -f, --force        перезаписывать существующие .md (по умолчанию они
                       пропускаются, чтобы не затереть правки).
    -o, --output DIR   складывать .md в эту папку, а не рядом с исходником.
    --only EXT[,EXT]   при маске/папке брать только эти расширения
                       (например: --only pdf  или  --only docx,xlsx).
    --keep-images      не трогать картинки: оставить base64 и ссылки-
                       заглушки картинок из .pptx (по умолчанию они
                       сворачиваются в компактный плейсхолдер).
    --unsafe-raw-markdown
                       не очищать потенциально опасные ссылки/HTML в
                       выходном Markdown (для доверенных источников).
    --allow-private-url
                       разрешить URL на localhost/private/link-local адреса.
    --url-timeout SEC  timeout сетевой загрузки URL (по умолчанию 20).
    --max-url-mb MB    максимум данных URL-ответа (по умолчанию 50).
    --no-frontmatter   не добавлять YAML-блок (source/converted) в начало.

Результат: то же имя, расширение .md (рядом с исходником или в папке -o);
при совпадении имён результата добавляется суффикс " (2)", " (3)"...
Расширение при вводе можно не указывать. Кодировка HTML (UTF-8, cp1251 и
др.) определяется автоматически.
"""

from __future__ import annotations

import glob
import argparse
import hashlib
import io
import ipaddress
import os
import re
import shlex
import socket
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

# markitdown тянет pydub, а тот при импорте предупреждает, что нет
# ffmpeg — для конвертации документов он не нужен, глушим.
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg")

try:
    from markitdown import MarkItDown
except ImportError:
    MarkItDown = None


def _missing_markitdown() -> None:
    # Не [all]: на Python 3.14 pip из-за него молча откатывается на 0.0.2.
    print("Библиотека markitdown не установлена. Установите командой:")
    print('  pip install "markitdown[pdf,docx,pptx,xlsx,xls,outlook]'
          '>=0.1.0,<1.0.0"')
    sys.exit(1)

# Windows-консоль бывает в cp1252/cp866 — переключаем вывод на UTF-8.
_encoding = sys.stdout.encoding
if _encoding and _encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

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
    r"(?i)^data:image/(png|jpeg|jpg|gif|webp|bmp);base64,[a-z0-9+/=\s]+$")
_MAX_REDIRECTS = 5
_DEFAULT_URL_TIMEOUT = 20.0
_DEFAULT_MAX_URL_MB = 50.0

_converter = None


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
            raise ValueError(f"расширение не может начинаться с '-': {raw}")
        if any(ch in part for ch in ("/", "\\", ":")):
            raise ValueError(f"расширение содержит путь: {raw}")
        if any(ord(ch) < 32 for ch in part):
            raise ValueError(f"расширение содержит управляющий символ: {raw}")
        if part.startswith("*."):
            part = part[1:]
        if part.startswith("."):
            part = part[1:]
        if not _EXTENSION.fullmatch(part):
            raise ValueError(f"недопустимое расширение: {raw}")
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
        where = "подпапках" if recursive else "папке"
        print(f"[ошибка] В {where} {root} подходящих файлов не найдено.")
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
            print(f"[ошибка] По маске {token} подходящих файлов не найдено.")
        return files

    # обычное имя: расширение можно не вводить
    if not path.exists() and path.suffix == "":
        for suffix in sorted(suffixes):
            candidate = Path(token + suffix)
            if candidate.exists():
                return [candidate]
    return [path]  # существование проверит конвертация


# --------------------------------------------------------------------------
# Сборка Markdown
# --------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", " ", value).strip()
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def _source_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def _source_id_for_path(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return _source_id("path", normalized)


def _source_id_for_url(url: str) -> str:
    return _source_id("url", url.strip())


def front_matter(source: str, title: str | None, tool: str,
                 source_path: str | None = None,
                 source_id: str | None = None) -> str:
    lines = ["---"]
    if title:
        lines.append(f"title: {_yaml_str(title)}")
    lines.append(f"source: {_yaml_str(source)}")
    lines.append(f"source_name: {_yaml_str(source)}")
    if source_path:
        lines.append(f"source_path: {_yaml_str(source_path)}")
    if source_id:
        lines.append(f"source_id: {_yaml_str(source_id)}")
    lines.append(f"converted: {date.today().isoformat()}")
    lines.append(f"generator: {tool} (MarkItDown)")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _img_placeholder(match: re.Match) -> str:
    alt = _markdown_label(match.group("alt") or "встроенное изображение")
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


def tidy(text: str, keep_images: bool, phantom_images: bool = False,
         safe_markdown: bool = True) -> str:
    """Прибирает вывод: чистит управляющие символы, убирает хвостовые
    пробелы, схлопывает пустые строки, обрезает края и (по умолчанию)
    сворачивает base64-картинки и битые картинки-заглушки из PPTX."""
    text = _CTRL_TO_SPACE.sub(" ", text)
    text = _CTRL_DROP.sub("", text)
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
            if source_id and existing_id == source_id:
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


def _emit(target: Path, result, source: str, frontmatter: bool,
          keep_images: bool, tool: str, note: str | None,
          phantom_images: bool = False,
          source_path: str | None = None,
          source_id: str | None = None,
          safe_markdown: bool = True) -> None:
    text = tidy(
        result.text_content,
        keep_images,
        phantom_images,
        safe_markdown=safe_markdown,
    )
    if frontmatter:
        title = getattr(result, "title", None)
        text = front_matter(source, title, tool, source_path, source_id) + text
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    extra = f" ({note})" if note else ""
    print(f"Готово: {target}{extra}")


# --------------------------------------------------------------------------
# Конвертация
# --------------------------------------------------------------------------

def _convert_reencoded(raw: bytes) -> tuple:
    """HTML не в UTF-8: определяем кодировку и гоним через UTF-8 temp."""
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
    except Exception:
        best = None
    if best is not None:
        text, enc = str(best), best.encoding
    else:
        text, enc = raw.decode("cp1251", errors="replace"), "cp1251"
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
    return result, f"перекодировано из {enc}"


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
        raise ValueError(f"{name} должен быть числом") from exc
    if number <= 0:
        raise ValueError(f"{name} должен быть больше 0")
    return number


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global


def _resolved_ips(hostname: str) -> set[str]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"не удалось разрешить host {hostname!r}") from exc
    return {info[4][0] for info in infos}


def _check_url_allowed(url: str, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("поддерживаются только http и https URL")
    if not parsed.hostname:
        raise ValueError("URL должен содержать имя хоста")
    if allow_private:
        return
    blocked = [ip for ip in _resolved_ips(parsed.hostname)
               if not _is_public_ip(ip)]
    if blocked:
        sample = ", ".join(sorted(blocked)[:3])
        raise ValueError(
            f"URL указывает на непубличный адрес ({sample}); "
            "используйте --allow-private-url только для доверенного сценария"
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
                f"URL-ответ больше лимита ({declared} байт > {max_bytes})"
            )

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"URL-ответ больше лимита ({max_bytes} байт)")
        chunks.append(chunk)
    return b"".join(chunks)


def _download_url(url: str, timeout: float, max_bytes: int,
                  allow_private: bool) -> tuple[bytes, str, str | None]:
    try:
        import requests
    except ImportError as exc:
        raise ValueError("для URL-режима нужен пакет requests") from exc

    current = url.strip()
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Accept": "text/markdown, text/html;q=0.9, "
                  "text/plain;q=0.8, */*;q=0.1",
        "User-Agent": "md-converters/1.0",
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
                        raise ValueError("редирект без заголовка Location")
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
        raise ValueError("слишком много редиректов")
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


def convert_file(path: Path, opts: dict) -> str:
    if not path.exists():
        print(f"[ошибка] Файл не найден: {path.resolve()}")
        return "fail"
    suffix = path.suffix.lower()
    if suffix not in opts["scan"]:
        print(f"[внимание] {path.name} — формат вне списка, пробую как есть.")

    dest = opts["out_dir"] or path.parent
    source_id = _source_id_for_path(path)
    target = _plan_target(
        path.stem, dest, opts["planned"], path.name, source_id,
        allow_legacy_source_match=opts["out_dir"] is None,
    )
    if target.exists() and not opts["force"]:
        print(f"[пропуск] {target.name} уже есть "
              "(-f / --force для перезаписи)")
        return "skip"

    print(f"Конвертирую {path.name} ...")
    try:
        result, note = _convert_file_data(path)
    except Exception as exc:
        print(f"[ошибка] Не удалось конвертировать {path.name}: {exc}")
        return "fail"
    try:
        _emit(target, result, path.name, opts["frontmatter"],
              opts["keep_images"], opts["tool"], note,
              phantom_images=(suffix == ".pptx"),
              source_path=str(path), source_id=source_id,
              safe_markdown=not opts.get("unsafe_raw_markdown", False))
    except OSError as exc:
        print(f"[ошибка] Не удалось записать {target.name}: {exc}")
        return "fail"
    return "ok"


def _url_stem(url: str) -> str:
    parsed = urlparse(url)
    name = parsed.path.rstrip("/").split("/")[-1] or parsed.netloc
    name = re.sub(r"[^\w.-]+", "-", name).strip("-")
    stem = Path(name).stem
    return stem or parsed.netloc.replace(".", "-") or "page"


def convert_url(url: str, opts: dict) -> str:
    dest = opts["out_dir"] or Path.cwd()
    source_id = _source_id_for_url(url)
    target = _plan_target(_url_stem(url), dest, opts["planned"], url,
                          source_id, allow_legacy_source_match=True)
    if target.exists() and not opts["force"]:
        print(f"[пропуск] {target.name} уже есть "
              "(-f / --force для перезаписи)")
        return "skip"
    print(f"Загружаю {url} ...")
    try:
        result, final_url = _convert_url_data(url, opts)
    except Exception as exc:
        print(f"[ошибка] Не удалось загрузить {url}: {exc}")
        return "fail"
    try:
        _emit(target, result, url, opts["frontmatter"],
              opts["keep_images"], opts["tool"], None,
              source_path=final_url, source_id=source_id,
              safe_markdown=not opts.get("unsafe_raw_markdown", False))
    except OSError as exc:
        print(f"[ошибка] Не удалось записать {target.name}: {exc}")
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
        parts = [f"сконвертировано {ok} из {len(items)}"]
        if skipped:
            parts.append(f"пропущено {skipped}")
        if failed:
            parts.append(f"ошибок {len(failed)}")
        print("Итого: " + ", ".join(parts) + ".")
        if failed:
            print("Не удалось обработать:")
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
    parser.add_argument("-o", "--output", dest="out_dir")
    parser.add_argument("--only")
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("patterns", nargs="*")
    try:
        parsed = parser.parse_args(tokens)
    except ValueError as exc:
        errors.append(f"[ошибка] Некорректные аргументы: {exc}")
        parsed = parser.parse_args([])

    if parsed.help:
        print(__doc__)
        sys.exit(0)

    out_dir = None
    if parsed.out_dir is not None:
        val = parsed.out_dir.strip().strip('"').strip("'")
        if val and not val.startswith("-"):
            out_dir = Path(val)
        else:
            errors.append("[ошибка] Флагу -o/--output нужен путь к папке.")

    only = None
    if parsed.only is not None:
        spec = parsed.only.strip().strip('"').strip("'")
        if not spec or spec.startswith("-"):
            errors.append("[ошибка] Флагу --only нужны расширения, "
                          "например: --only pdf,docx.")
        else:
            try:
                only = _suffix_set(spec) or None
            except ValueError as exc:
                errors.append(f"[ошибка] Некорректный --only: {exc}")
            if only is None and not errors:
                errors.append("[ошибка] Флагу --only нужны расширения, "
                              "например: --only pdf,docx.")
    try:
        url_timeout = _positive_float(parsed.url_timeout, "--url-timeout")
    except ValueError as exc:
        errors.append(f"[ошибка] {exc}")
        url_timeout = _DEFAULT_URL_TIMEOUT

    try:
        max_url_mb = _positive_float(parsed.max_url_mb, "--max-url-mb")
    except ValueError as exc:
        errors.append(f"[ошибка] {exc}")
        max_url_mb = _DEFAULT_MAX_URL_MB

    return {
        "patterns": parsed.patterns, "force": parsed.force,
        "recursive": parsed.recursive, "frontmatter": parsed.frontmatter,
        "keep_images": parsed.keep_images,
        "unsafe_raw_markdown": parsed.unsafe_raw_markdown,
        "allow_private_url": parsed.allow_private_url,
        "url_timeout": url_timeout,
        "max_url_mb": max_url_mb,
        "out_dir": out_dir, "only": only, "errors": errors,
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
        "out_dir": parsed["out_dir"],
        "scan": scan,
        "tool": _tool_name(only),
        "planned": set(),
    }


def _items_from(patterns: list, recursive: bool, scan: set) -> list:
    items = []
    seen = set()
    for pattern in patterns:
        if _is_url(pattern):
            items.append(pattern.strip().strip('"').strip("'"))
            continue
        for path in collect(pattern, recursive, scan):
            key = str(path).lower()
            if key not in seen:
                seen.add(key)
                items.append(path)
    return items


def interactive(default_only: list | None) -> None:
    print("=== Универсальный конвертер -> Markdown ===")
    print("Введите файл, папку, маску или URL и нажмите Enter.")
    print("Форматы: PDF, HTML, Word, Excel, PowerPoint, CSV и др.")
    print("Примеры:  *   |   C:\\reports -r   |   https://site/page")
    print("Пустая строка или Ctrl+C — выход.")
    while True:
        try:
            line = input("\nФайл> ")
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
                            opts["scan"])
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
                    _plan_target(_url_stem(it),
                                 opts["out_dir"] or Path.cwd(), sim, it)
                    continue
                t = _plan_target(it.stem, opts["out_dir"] or it.parent,
                                 sim, it.name)
                if t.exists():
                    existing.append(it)
            if existing:
                answer = input(
                    f"{len(existing)} файл(ов) уже имеют .md. "
                    "Перезаписать? (y = да / Enter = пропустить): "
                )
                force = answer.strip().lower() in ("y", "yes", "д", "да")
        opts["force"] = force
        run(items, opts)


def _main(argv: list, default_only: list | None = None) -> int:
    parsed = _parse(argv)
    if parsed["errors"]:
        for msg in parsed["errors"]:
            print(msg)
        return 2
    if parsed["patterns"]:
        opts = _build_opts(parsed, default_only)
        items = _items_from(parsed["patterns"], parsed["recursive"],
                            opts["scan"])
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
