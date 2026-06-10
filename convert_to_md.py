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
    --no-frontmatter   не добавлять YAML-блок (source/converted) в начало.

Результат: то же имя, расширение .md (рядом с исходником или в папке -o).
Расширение при вводе можно не указывать. Кодировка HTML (UTF-8, cp1251 и
др.) определяется автоматически.
"""

import glob
import os
import re
import shlex
import sys
import tempfile
import warnings
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

# markitdown тянет pydub, а тот при импорте предупреждает, что нет
# ffmpeg — для конвертации документов он не нужен, глушим.
warnings.filterwarnings("ignore", message="Couldn't find ffmpeg")

try:
    from markitdown import MarkItDown
except ImportError:
    print("Библиотека markitdown не установлена.")
    print('Установите командой:  pip install "markitdown[all]"')
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

# Папки, которые при рекурсии не имеют смысла — не заходим туда.
EXCLUDE_DIRS = {
    "node_modules", ".next", ".git", ".svn", ".hg",
    "__pycache__", ".venv", "venv", "dist", "build", ".idea",
}

# Встроенная картинка в виде data-URI: огромный base64 в Markdown.
_DATA_IMG = re.compile(r"!\[(?P<alt>[^\]]*)\]\(data:image/[^)]*\)")

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

_converter = None


def _md() -> "MarkItDown":
    global _converter
    if _converter is None:
        _converter = MarkItDown()
    return _converter


def _is_url(token) -> bool:
    if not isinstance(token, str):
        return False
    clean = token.strip().strip('"').strip("'")
    return bool(re.match(r"(?i)^https?://", clean))


def _suffix_set(spec: str) -> set:
    """'pdf,docx' -> {'.pdf', '.docx'}."""
    result = set()
    for part in spec.split(","):
        part = part.strip().lower().lstrip("*")
        if not part:
            continue
        result.add(part if part.startswith(".") else "." + part)
    return result


def _tool_name(restrict: "set | None") -> str:
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


def scan_dir(root: Path, recursive: bool, suffixes: set) -> list[Path]:
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


def _gather_glob(pattern: str, recursive: bool, suffixes: set) -> list[Path]:
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


def collect(token: str, recursive: bool, suffixes: set) -> list[Path]:
    """Раскрывает имя/папку/маску в список путей к файлам."""
    token = token.strip().strip('"').strip("'")
    if not token:
        return []

    path = Path(token)
    if path.is_dir():
        return scan_dir(path, recursive, suffixes)

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
    value = value.replace("\n", " ").strip()
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def front_matter(source: str, title: "str | None", tool: str) -> str:
    lines = ["---"]
    if title:
        lines.append(f"title: {_yaml_str(title)}")
    lines.append(f"source: {_yaml_str(source)}")
    lines.append(f"converted: {date.today().isoformat()}")
    lines.append(f"generator: {tool} (MarkItDown)")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _img_placeholder(match: "re.Match") -> str:
    return f"![{match.group('alt') or 'встроенное изображение'}]()"


def tidy(text: str, keep_images: bool, phantom_images: bool = False) -> str:
    """Прибирает вывод: чистит управляющие символы, убирает хвостовые
    пробелы, схлопывает пустые строки, обрезает края и (по умолчанию)
    сворачивает base64-картинки и битые картинки-заглушки из PPTX."""
    text = _CTRL_TO_SPACE.sub(" ", text)
    text = _CTRL_DROP.sub("", text)
    if not keep_images:
        text = _DATA_IMG.sub(_img_placeholder, text)
        if phantom_images:
            text = _PHANTOM_IMG.sub(_img_placeholder, text)
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


def _plan_target(stem: str, dest_dir: Path, flatten: bool,
                 planned: set) -> Path:
    """Путь к .md; при flatten разводит совпадения именами (2), (3)..."""
    target = dest_dir / (stem + ".md")
    if flatten:
        n = 2
        while str(target).lower() in planned:
            target = dest_dir / f"{stem} ({n}).md"
            n += 1
    planned.add(str(target).lower())
    return target


def _emit(target: Path, result, source: str, frontmatter: bool,
          keep_images: bool, tool: str, note: "str | None",
          phantom_images: bool = False) -> None:
    text = tidy(result.text_content, keep_images, phantom_images)
    if frontmatter:
        title = getattr(result, "title", None)
        text = front_matter(source, title, tool) + text
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    extra = f" ({note})" if note else ""
    print(f"Готово: {target}{extra}")


# --------------------------------------------------------------------------
# Конвертация
# --------------------------------------------------------------------------

def _convert_reencoded(raw: bytes):
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
        os.close(fd)
        result = _md().convert(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return result, f"перекодировано из {enc}"


def _convert_file_data(path: Path):
    """(result, note). Для HTML — с автоопределением кодировки."""
    if path.suffix.lower() in (".html", ".htm"):
        raw = path.read_bytes()
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return _convert_reencoded(raw)
    return _md().convert(str(path)), None


def convert_file(path: Path, opts: dict) -> str:
    if not path.exists():
        print(f"[ошибка] Файл не найден: {path.resolve()}")
        return "fail"
    suffix = path.suffix.lower()
    if suffix not in opts["scan"]:
        print(f"[внимание] {path.name} — формат вне списка, пробую как есть.")

    dest = opts["out_dir"] or path.parent
    target = _plan_target(path.stem, dest, opts["out_dir"] is not None,
                          opts["planned"])
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
              phantom_images=(suffix == ".pptx"))
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
    target = _plan_target(_url_stem(url), dest, True, opts["planned"])
    if target.exists() and not opts["force"]:
        print(f"[пропуск] {target.name} уже есть "
              "(-f / --force для перезаписи)")
        return "skip"
    print(f"Загружаю {url} ...")
    try:
        result = _md().convert_url(url)
    except Exception as exc:
        print(f"[ошибка] Не удалось загрузить {url}: {exc}")
        return "fail"
    try:
        _emit(target, result, url, opts["frontmatter"],
              opts["keep_images"], opts["tool"], None)
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

def _parse(tokens: list):
    patterns = []
    force = recursive = keep_images = False
    frontmatter = True
    out_dir = None
    only = None
    rest = False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if rest:
            patterns.append(t)
        elif t == "--":
            rest = True
        elif t in ("-f", "--force"):
            force = True
        elif t in ("-r", "--recursive"):
            recursive = True
        elif t == "--no-frontmatter":
            frontmatter = False
        elif t == "--keep-images":
            keep_images = True
        elif t in ("-o", "--output"):
            i += 1
            if i < len(tokens):
                out_dir = Path(tokens[i].strip().strip('"').strip("'"))
        elif t.startswith("--output="):
            out_dir = Path(t.split("=", 1)[1].strip('"').strip("'"))
        elif t == "--only":
            i += 1
            if i < len(tokens):
                only = _suffix_set(tokens[i])
        elif t.startswith("--only="):
            only = _suffix_set(t.split("=", 1)[1])
        elif t in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            patterns.append(t)
        i += 1
    return {
        "patterns": patterns, "force": force, "recursive": recursive,
        "frontmatter": frontmatter, "keep_images": keep_images,
        "out_dir": out_dir, "only": only,
    }


def _build_opts(parsed: dict, default_only: "list | None") -> dict:
    only = parsed["only"]
    if only is None and default_only:
        only = _suffix_set(",".join(default_only))
    scan = only or SUPPORTED_SUFFIXES
    return {
        "force": parsed["force"],
        "frontmatter": parsed["frontmatter"],
        "keep_images": parsed["keep_images"],
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


def interactive(default_only: "list | None") -> None:
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
        opts = _build_opts(parsed, default_only)
        items = _items_from(parsed["patterns"], parsed["recursive"],
                            opts["scan"])
        if not items:
            continue

        force = parsed["force"]
        if not force:
            file_items = [i for i in items if not _is_url(i)]
            dest = opts["out_dir"]
            existing = [
                i for i in file_items
                if ((dest or i.parent) / (i.stem + ".md")).exists()
            ]
            if existing:
                answer = input(
                    f"{len(existing)} файл(ов) уже имеют .md. "
                    "Перезаписать? (y = да / Enter = пропустить): "
                )
                force = answer.strip().lower() in ("y", "yes", "д", "да")
        opts["force"] = force
        run(items, opts)


def _main(argv: list, default_only: "list | None" = None) -> int:
    parsed = _parse(argv)
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
