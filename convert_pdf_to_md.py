# -*- coding: utf-8 -*-
"""Конвертация PDF в Markdown через MarkItDown (Microsoft).

Использование:
    python convert_pdf_to_md.py                     — интерактивный режим:
        утилита просит имя файла; Enter — конвертирует; пустая строка — выход.
    python convert_pdf_to_md.py file.pdf [file2.pdf ...]
        — пакетный режим: конвертирует перечисленные файлы.

Результат кладётся рядом с исходником: то же имя, расширение .md.
Расширение .pdf при вводе можно не указывать — подставится само.
"""

import sys
from pathlib import Path

try:
    from markitdown import MarkItDown
except ImportError:
    print("Библиотека markitdown не установлена.")
    print('Установите командой:  pip install "markitdown[pdf]"')
    sys.exit(1)

# Windows-консоль бывает в cp1252/cp866 — переключаем вывод на UTF-8,
# иначе print с кириллицей падает с UnicodeEncodeError.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

_converter = None  # создаётся один раз при первой конвертации


def convert(raw_name: str) -> bool:
    """Конвертирует один PDF в .md рядом с ним. Возвращает True при успехе."""
    global _converter

    # убираем кавычки — они появляются при перетаскивании файла в консоль
    name = raw_name.strip().strip('"').strip("'")
    if not name:
        return False

    pdf_path = Path(name)
    # расширение можно не вводить: если такого файла нет, пробуем имя + ".pdf"
    if not pdf_path.exists() and pdf_path.suffix.lower() != ".pdf":
        candidate = Path(name + ".pdf")
        if candidate.exists():
            pdf_path = candidate

    if not pdf_path.exists():
        print(f"[ошибка] Файл не найден: {pdf_path.resolve()}")
        return False
    if pdf_path.suffix.lower() != ".pdf":
        print(f"[внимание] {pdf_path.name} — не PDF, пробую конвертировать как есть.")

    output_file = pdf_path.with_suffix(".md")
    print(f"Конвертирую {pdf_path.name} ...")
    try:
        if _converter is None:
            _converter = MarkItDown()
        result = _converter.convert(str(pdf_path))
    except Exception as exc:
        print(f"[ошибка] Не удалось конвертировать {pdf_path.name}: {exc}")
        return False

    try:
        output_file.write_text(result.text_content, encoding="utf-8")
    except OSError as exc:
        print(f"[ошибка] Не удалось записать {output_file.name}: {exc}")
        return False

    print(f"Готово: {output_file.resolve()}")
    return True


def interactive() -> None:
    print("=== Конвертер PDF -> Markdown ===")
    print("Введите имя PDF-файла и нажмите Enter.")
    print("Пустая строка или Ctrl+C — выход.")
    while True:
        try:
            name = input("\nPDF-файл> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not name.strip():
            break
        convert(name)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        results = [convert(arg) for arg in sys.argv[1:]]
        sys.exit(0 if all(results) else 1)
    interactive()
