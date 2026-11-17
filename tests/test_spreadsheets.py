"""Таблицы офисных форматов: значения ячеек доходят до Markdown как
есть. Книги и CSV создаются в tmp_path, реальных документов нет."""
import datetime

import pytest

import convert_to_md


def _opts(out):
    return {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "sandbox": False,
        "scan": {".xlsx", ".csv"}, "tool": "tomd", "planned": set(),
    }


def test_xlsx_text_cells_stay_text(tmp_path):
    # pandas.read_excel угадывал типы: «00123» -> 123, «NA»/«NULL» ->
    # NaN, пустая ячейка -> «NaN». Текстовая ячейка — это текст.
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Коды"
    sheet.append(["code", "flag", "num", "note", "day"])
    sheet.append(["00123", "NA", 5, None, datetime.datetime(2026, 11, 5)])
    sheet.append(["00456", "NULL", 6.5, "x", None])
    src = tmp_path / "codes.xlsx"
    book.save(src)
    out = tmp_path / "out"

    assert convert_to_md.convert_file(src, _opts(out)) == "ok"
    md = (out / "codes.md").read_text(encoding="utf-8")

    assert md.startswith("## Коды\n| code | flag | num | note | day |")
    assert "| 00123 | NA | 5 |  | 2026-11-05 |" in md
    assert "| 00456 | NULL | 6.5 | x |  |" in md
    assert "NaN" not in md


def test_xlsx_falls_back_to_markitdown_reader_on_error(tmp_path,
                                                      monkeypatch):
    # Если чтение «как есть» падает, конвертация не ломается: MarkItDown
    # переходит к своему конвертеру (с его выводом типов).
    openpyxl = pytest.importorskip("openpyxl")
    pandas = pytest.importorskip("pandas")
    book = openpyxl.Workbook()
    book.active.append(["code"])
    book.active.append(["00123"])
    src = tmp_path / "fallback.xlsx"
    book.save(src)
    real = pandas.read_excel

    def read_excel(*args, **kwargs):
        if kwargs.get("dtype") is object:
            raise TypeError("simulated reader failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(pandas, "read_excel", read_excel)
    out = tmp_path / "out"

    assert convert_to_md.convert_file(src, _opts(out)) == "ok"
    assert "| 123 |" in (out / "fallback.md").read_text(encoding="utf-8")


def test_csv_cells_with_pipe_and_newline_keep_table_shape(tmp_path):
    # «|» в ячейке не должен становиться разделителем столбцов, перенос
    # строки внутри ячейки — рвать строку таблицы. Делает сам
    # MarkItDown (>=0.1.9, нижняя граница зависимости); тест держит
    # это поведение.
    src = tmp_path / "pipes.csv"
    src.write_text('h1,h2\nТест,"a|b"\nx,"первая\nвторая"\n',
                   encoding="utf-8")
    out = tmp_path / "out"

    assert convert_to_md.convert_file(src, _opts(out)) == "ok"
    md = (out / "pipes.md").read_text(encoding="utf-8")

    assert md == (
        "| h1 | h2 |\n| --- | --- |\n"
        "| Тест | a\\|b |\n| x | первая вторая |\n"
    )
