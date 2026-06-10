# -*- coding: utf-8 -*-
"""Конвертация PDF в Markdown через MarkItDown (Microsoft).

Использование:
    python convert_pdf_to_md.py                     — интерактивный режим:
        просит имя файла/маску; Enter — конвертирует; пустая строка — выход.
    python convert_pdf_to_md.py file.pdf [...]      — конвертирует файлы.
    python convert_pdf_to_md.py *                   — все PDF в папке.
    python convert_pdf_to_md.py C:\\docs             — все PDF в папке.
    python convert_pdf_to_md.py C:\\docs -r          — и во вложенных папках.

Флаги:
    -r, --recursive   обходить вложенные папки (node_modules/.git и т.п.
                      пропускаются автоматически).
    -f, --force       перезаписывать уже существующие .md (по умолчанию
                      такие файлы пропускаются, чтобы не затереть правки).
    --no-frontmatter  не добавлять YAML-блок (source/converted) в начало.

В интерактивном режиме флаги -r/-f тоже можно дописать в строку ввода;
если рядом уже есть .md, утилита спросит, перезаписывать ли их.

Результат кладётся рядом с исходником: то же имя, расширение .md.
Расширение .pdf при вводе можно не указывать — подставится само.
"""

import glob
import os
import sys
from datetime import date
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError:
    print("Библиотека markitdown не установлена.")
    print('Установите командой:  pip install "markitdown[pdf]"')
    sys.exit(1)

# Windows-консоль бывает в cp1252/cp866 — переключаем вывод на UTF-8,
# иначе print с кириллицей падает с UnicodeEncodeError.
_encoding = sys.stdout.encoding
if _encoding and _encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

PDF_SUFFIXES = (".pdf",)

# Папки, которые при рекурсии не имеют смысла — не лезем туда.
EXCLUDE_DIRS = {
    "node_modules", ".next", ".git", ".svn", ".hg",
    "__pycache__", ".venv", "venv", "dist", "build", ".idea",
}

_converter = None  # MarkItDown создаётся один раз при первой конвертации


def _md() -> "MarkItDown":
    global _converter
    if _converter is None:
        _converter = MarkItDown()
    return _converter


# --------------------------------------------------------------------------
# Поиск файлов
# --------------------------------------------------------------------------

def _excluded(path: Path) -> bool:
    """True, если в пути встречается служебная папка из EXCLUDE_DIRS."""
    return any(part in EXCLUDE_DIRS for part in path.parts)


def scan_dir(root: Path, recursive: bool) -> list[Path]:
    """Все PDF-файлы в папке (и во вложенных, если recursive)."""
    files: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            # не спускаемся в служебные папки
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for name in filenames:
                if Path(name).suffix.lower() in PDF_SUFFIXES:
                    files.append(Path(dirpath) / name)
    else:
        for item in root.iterdir():
            if item.is_file() and item.suffix.lower() in PDF_SUFFIXES:
                files.append(item)
    if not files:
        where = "подпапках" if recursive else "папке"
        print(f"[ошибка] В {where} {root} PDF-файлы не найдены.")
    return sorted(files)


def _gather_glob(pattern: str, recursive: bool) -> list[Path]:
    """PDF-файлы по glob-шаблону (служебные папки отфильтрованы)."""
    matches = [Path(p) for p in glob.glob(pattern, recursive=recursive)]
    files = [
        p for p in matches
        if p.is_file()
        and p.suffix.lower() in PDF_SUFFIXES
        and not _excluded(p)
    ]
    # маска без расширения (например, doc-*) — подставляем его сами
    if not files:
        for suffix in PDF_SUFFIXES:
            for p in glob.glob(pattern + suffix, recursive=recursive):
                path = Path(p)
                if path.is_file() and not _excluded(path):
                    files.append(path)
    return sorted(set(files))


def collect(token: str, recursive: bool = False) -> list[Path]:
    """Раскрывает имя/папку/маску в список путей к PDF-файлам."""
    token = token.strip().strip('"').strip("'")
    if not token:
        return []

    path = Path(token)
    if path.is_dir():
        return scan_dir(path, recursive)

    if any(ch in token for ch in "*?["):
        pattern = token
        # при -r и обычной маске ищем её во всех подпапках
        if recursive and "**" not in token:
            parent = path.parent
            if str(parent) in ("", "."):
                pattern = f"**/{path.name}"
            else:
                pattern = str(parent / "**" / path.name)
        files = _gather_glob(pattern, recursive or "**" in pattern)
        if not files:
            print(f"[ошибка] По маске {token} PDF-файлы не найдены.")
        return files

    # обычное имя: расширение можно не вводить
    if (not path.exists()
            and path.suffix.lower() not in PDF_SUFFIXES):
        for suffix in PDF_SUFFIXES:
            candidate = Path(token + suffix)
            if candidate.exists():
                return [candidate]
    return [path]  # существование проверит convert_one()


# --------------------------------------------------------------------------
# Конвертация
# --------------------------------------------------------------------------

def _yaml_str(value: str) -> str:
    """Безопасный YAML-скаляр в двойных кавычках."""
    value = value.replace("\n", " ").strip()
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def front_matter(source_name: str, title: str | None) -> str:
    """YAML-блок с источником и датой конвертации."""
    lines = ["---"]
    if title:
        lines.append(f"title: {_yaml_str(title)}")
    lines.append(f"source: {_yaml_str(source_name)}")
    lines.append(f"converted: {date.today().isoformat()}")
    lines.append("generator: pdf2md (MarkItDown)")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def tidy(text: str) -> str:
    """Прибирает вывод MarkItDown: убирает хвостовые пробелы,
    схлопывает идущие подряд пустые строки и обрезает края."""
    out: list[str] = []
    blank = False
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        if line == "":
            if not blank:          # оставляем максимум одну пустую строку
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


def convert_one(path: Path, force: bool, frontmatter: bool) -> str:
    """Конвертирует один файл. Возвращает 'ok' | 'skip' | 'fail'."""
    if not path.exists():
        print(f"[ошибка] Файл не найден: {path.resolve()}")
        return "fail"
    if path.suffix.lower() not in PDF_SUFFIXES:
        print(f"[внимание] {path.name} — не PDF, пробую как есть.")

    output_file = path.with_suffix(".md")
    if output_file.exists() and not force:
        print(f"[пропуск] {output_file.name} уже есть "
              "(-f / --force для перезаписи)")
        return "skip"

    print(f"Конвертирую {path.name} ...")
    try:
        result = _md().convert(str(path))
    except Exception as exc:
        print(f"[ошибка] Не удалось конвертировать {path.name}: {exc}")
        return "fail"

    text = tidy(result.text_content)
    if frontmatter:
        title = getattr(result, "title", None)
        text = front_matter(path.name, title) + text

    try:
        output_file.write_text(text, encoding="utf-8")
    except OSError as exc:
        print(f"[ошибка] Не удалось записать {output_file.name}: {exc}")
        return "fail"

    print(f"Готово: {output_file.resolve()}")
    return "ok"


def run(files: list[Path], force: bool, frontmatter: bool) -> list[Path]:
    """Конвертирует список файлов, печатает итог. Возвращает список
    файлов, которые не удалось сконвертировать."""
    ok = skipped = 0
    failed: list[Path] = []
    for path in files:
        status = convert_one(path, force, frontmatter)
        if status == "ok":
            ok += 1
        elif status == "skip":
            skipped += 1
        else:
            failed.append(path)

    if len(files) > 1:
        parts = [f"сконвертировано {ok} из {len(files)}"]
        if skipped:
            parts.append(f"пропущено {skipped}")
        if failed:
            parts.append(f"ошибок {len(failed)}")
        print("Итого: " + ", ".join(parts) + ".")
        if failed:
            print("Не удалось сконвертировать:")
            for path in failed:
                print(f"  - {path}")
    return failed


# --------------------------------------------------------------------------
# Разбор аргументов / режимы
# --------------------------------------------------------------------------

def _parse_flags(tokens: list[str]):
    """Делит аргументы на (шаблоны, force, recursive, frontmatter)."""
    patterns: list[str] = []
    force = recursive = False
    frontmatter = True
    only_patterns = False
    for token in tokens:
        if only_patterns:
            patterns.append(token)
        elif token == "--":
            only_patterns = True
        elif token in ("-f", "--force"):
            force = True
        elif token in ("-r", "--recursive"):
            recursive = True
        elif token == "--no-frontmatter":
            frontmatter = False
        elif token in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        else:
            patterns.append(token)
    return patterns, force, recursive, frontmatter


def interactive(frontmatter: bool) -> None:
    print("=== Конвертер PDF -> Markdown ===")
    print("Введите имя файла, папку или маску и нажмите Enter.")
    print("Примеры:  *   |   doc-*   |   C:\\docs -r")
    print("Пустая строка или Ctrl+C — выход.")
    while True:
        try:
            line = input("\nPDF-файл> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line.strip():
            break

        patterns, force, recursive, _ = _parse_flags(line.split())
        files: list[Path] = []
        for pattern in patterns:
            files += collect(pattern, recursive)
        if not files:
            continue

        # если рядом уже есть .md — спрашиваем один раз на всю пачку
        if not force:
            existing = [
                f for f in files if f.with_suffix(".md").exists()
            ]
            if existing:
                answer = input(
                    f"{len(existing)} файл(ов) уже имеют .md. "
                    "Перезаписать? (y = да / Enter = пропустить): "
                )
                force = answer.strip().lower() in ("y", "yes", "д", "да")
        run(files, force, frontmatter)


if __name__ == "__main__":
    patterns, force, recursive, frontmatter = _parse_flags(sys.argv[1:])
    if patterns:
        files: list[Path] = []
        seen: set[str] = set()
        for pattern in patterns:
            for path in collect(pattern, recursive):
                key = str(path).lower()
                if key not in seen:
                    seen.add(key)
                    files.append(path)
        failed = run(files, force, frontmatter)
        sys.exit(1 if (failed or not files) else 0)
    interactive(frontmatter)
