"""PDF-таблицы через pdfplumber: чистые функции обработки строк, склейка
переносных таблиц, поле front-matter, флаг --pdf-tables и интеграция в
convert_file. Большинство тестов — на списках строк и мок-результатах
(как в test_pdf_text_layer); плюс несколько на реальном zero-dep PDF,
чтобы покрыть саму pdfplumber-glue (find_tables/bbox/extract)."""
from types import SimpleNamespace

import random
import re

import pytest

import convert_to_md as c


def _ruled_table_pdf_bytes() -> bytes:
    """Минимальный валидный PDF с разлинованной таблицей 2 кол. x 3 стр.
    Сделан вручную, без сторонних библиотек (как tools/make_image_only_
    pdf.py), чтобы не тащить reportlab в зависимости тестов."""
    content = (
        b"BT /F1 11 Tf 105 705 Td (Name) Tj ET\n"
        b"BT /F1 11 Tf 225 705 Td (Value) Tj ET\n"
        b"BT /F1 11 Tf 105 685 Td (alpha) Tj ET\n"
        b"BT /F1 11 Tf 225 685 Td (1) Tj ET\n"
        b"BT /F1 11 Tf 105 665 Td (beta) Tj ET\n"
        b"BT /F1 11 Tf 225 665 Td (2) Tj ET\n"
        b"0.5 w\n"
        b"100 660 m 100 720 l S\n"
        b"220 660 m 220 720 l S\n"
        b"340 660 m 340 720 l S\n"
        b"100 720 m 340 720 l S\n"
        b"100 700 m 340 700 l S\n"
        b"100 680 m 340 680 l S\n"
        b"100 660 m 340 660 l S\n"
    )
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref_pos))
    return out


# --- _table_to_gfm ---------------------------------------------------------

def test_table_to_gfm_basic_shape():
    md = c._table_to_gfm([["A", "B"], ["1", "2"]])
    assert md == "| A | B |\n| --- | --- |\n| 1 | 2 |"


def test_table_to_gfm_escapes_pipe_and_collapses_newline():
    md = c._table_to_gfm([["a|b", "x\ny"], ["1", "2"]])
    assert "a\\|b" in md
    assert "x y" in md and "\n2 |" not in md.split("---")[0]


def test_table_to_gfm_pads_ragged_rows_and_none():
    md = c._table_to_gfm([["a", "b", "c"], ["1", None]])
    # рваная строка дополнена до 3 колонок, None -> пусто
    assert md.splitlines()[-1] == "| 1 |  |  |"


# --- _looks_like_table -----------------------------------------------------

def test_looks_like_table_rejects_single_column():
    assert c._looks_like_table([["a"], ["b"], ["c"]]) is False


def test_looks_like_table_rejects_prose():
    # >50% ячеек — длинный текст (проза), а не табличные данные.
    long = "ы" * 80
    rows = [[long, long], [long, "x"]]
    assert c._looks_like_table(rows) is False


def test_looks_like_table_accepts_label_plus_long_phrase():
    # Таблицы фраз: короткая метка + длинная фраза (ровно 50% длинных) —
    # это валидная таблица, её НЕ отсекаем.
    phrase = "ц" * 90
    rows = [["Момент", "Фраза"], ["Старт", phrase], ["Финал", phrase]]
    assert c._looks_like_table(rows) is True


def test_looks_like_table_accepts_real():
    rows = [["H1", "H2"], ["a", "b"], ["c", "d"]]
    assert c._looks_like_table(rows) is True


# --- _drop_empty_columns ---------------------------------------------------

def test_drop_empty_columns_removes_blank_middle():
    rows = [["a", "", "b"], ["c", " ", "d"]]
    assert c._drop_empty_columns(rows) == [["a", "b"], ["c", "d"]]


def test_drop_empty_columns_noop_keeps_object():
    rows = [["a", "b"], ["c", "d"]]
    assert c._drop_empty_columns(rows) is rows


# --- _segment_table_rows ---------------------------------------------------

def test_segment_splits_lead_mid_and_trail_prose():
    rows = [
        ["Заголовок", ""],        # lead prose (1 ячейка)
        ["H1", "H2"],             # table
        ["a", "b"],
        ["Раздел 2", ""],         # mid prose
        ["c", "d"],               # table
        ["Хвост", ""],            # trail prose
    ]
    seg = c._segment_table_rows(rows)
    kinds = [k for k, _ in seg]
    assert kinds == ["text", "table", "text", "table", "text"]
    assert seg[0][1] == "Заголовок"
    assert seg[1][1] == [["H1", "H2"], ["a", "b"]]


# --- _join_continued_tables ------------------------------------------------

def test_join_merges_repeated_header_across_pages():
    blocks = [
        ("table", [["M", "S"], ["a", "b"]]),
        ("table", [["M", "S"], ["c", "d"]]),  # повтор заголовка = продолжение
    ]
    merged = c._join_continued_tables(blocks)
    assert len(merged) == 1
    assert merged[0][1] == [["M", "S"], ["a", "b"], ["c", "d"]]


def test_join_keeps_distinct_tables_apart():
    blocks = [
        ("table", [["M", "S"], ["a", "b"]]),
        ("table", [["X", "Y"], ["c", "d"]]),  # другой заголовок
    ]
    assert len(c._join_continued_tables(blocks)) == 2


def test_join_does_not_merge_across_text_block():
    blocks = [
        ("table", [["M", "S"], ["a", "b"]]),
        ("text", "между"),
        ("table", [["M", "S"], ["c", "d"]]),
    ]
    assert len(c._join_continued_tables(blocks)) == 3


# --- front-matter поле pdf_tables ------------------------------------------

def test_front_matter_includes_pdf_tables_when_provided():
    fm = c.front_matter("r.pdf", None, "tomd", pdf_tables=3)
    assert "pdf_tables: 3" in fm


def test_front_matter_omits_pdf_tables_by_default():
    fm = c.front_matter("r.pdf", None, "tomd")
    assert "pdf_tables" not in fm


# --- флаг --pdf-tables -----------------------------------------------------

def test_parse_pdf_tables_default_auto():
    parsed = c._parse(["file.pdf"])
    assert parsed["pdf_tables"] == "auto"
    assert parsed["errors"] == []


def test_parse_pdf_tables_off():
    parsed = c._parse(["file.pdf", "--pdf-tables", "off"])
    assert parsed["pdf_tables"] == "off"
    assert parsed["errors"] == []


def test_parse_pdf_tables_rejects_bogus():
    parsed = c._parse(["file.pdf", "--pdf-tables", "bogus"])
    assert parsed["errors"]


# --- _pdf_tables_result охранные случаи ------------------------------------

def test_pdf_tables_result_none_without_pdfplumber(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "pdfplumber", None)
    assert c._pdf_tables_result(tmp_path / "x.pdf") is None


# --- интеграция в convert_file --------------------------------------------

def _pdf_opts(out):
    return {
        "force": True, "frontmatter": True, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "scan": {".pdf"},
        "tool": "tomd", "planned": set(), "pdf_tables": "auto",
    }


def test_convert_file_uses_pdf_tables_path(tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()

    result = c._PdfResult("| A | B |\n| --- | --- |\n| 1 | 2 |\n", 1)
    monkeypatch.setattr(c, "_pdf_tables_result", lambda p: result)
    monkeypatch.setattr(c, "_pdf_page_count", lambda p: 1)

    def fail(p):
        raise AssertionError("MarkItDown path must not run when tables found")
    monkeypatch.setattr(c, "_convert_file_data", fail)

    assert c.convert_file(src, _pdf_opts(out)) == "ok"
    body = (out / "doc.md").read_text(encoding="utf-8")
    assert "pdf_tables: 1" in body
    assert "| A | B |" in body


def test_convert_file_pdf_tables_off_skips_pdfplumber(tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()
    seen = {"pdf": False}

    def spy(p):
        seen["pdf"] = True
        return None
    monkeypatch.setattr(c, "_pdf_tables_result", spy)
    monkeypatch.setattr(c, "_pdf_page_count", lambda p: 1)
    fake = SimpleNamespace(text_content="plain text " * 20, title=None)
    monkeypatch.setattr(c, "_convert_file_data", lambda p: (fake, None))

    opts = _pdf_opts(out)
    opts["pdf_tables"] = "off"
    assert c.convert_file(src, opts) == "ok"
    assert seen["pdf"] is False  # ветку pdfplumber не трогали
    body = (out / "doc.md").read_text(encoding="utf-8")
    assert "pdf_tables:" not in body  # двоеточие — само поле, не путь


# --- реальный PDF: покрываем pdfplumber-glue (без моков) -------------------

def _wrap_pdf(content: bytes, font_extra: bytes = b"",
              media: bytes = b"0 0 595 842") -> bytes:
    """Оборачивает поток содержимого в минимальный валидный PDF (1 стр.,
    шрифт Helvetica). Используется для side-by-side фикстуры.
    font_extra — добавка в словарь шрифта (например, кодировка)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [%s] " % media +
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica %s>>"
        % font_extra,
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref_pos))
    return out


def _side_by_side_tables_pdf() -> bytes:
    """Две разлинованные таблицы 3x2 рядом по горизонтали (одна Y)."""
    txt = []
    for label, bx in (("L", 75), ("R", 325)):
        col2 = bx + 90
        cells = [(label + "1", bx, 705), (label + "2", col2, 705),
                 ("a" + label, bx, 685), ("b" + label, col2, 685),
                 ("c" + label, bx, 665), ("d" + label, col2, 665)]
        for t, x, y in cells:
            txt.append(b"BT /F1 10 Tf %d %d Td (%s) Tj ET\n"
                       % (x, y, t.encode()))
    lines = [b"0.5 w\n"]
    for lx in (70, 160, 250, 320, 410, 500):
        lines.append(b"%d 660 m %d 720 l S\n" % (lx, lx))
    for ly in (720, 700, 680, 660):
        lines.append(b"70 %d m 250 %d l S\n" % (ly, ly))
        lines.append(b"320 %d m 500 %d l S\n" % (ly, ly))
    return _wrap_pdf(b"".join(txt) + b"".join(lines))


def test_pdf_tables_result_keeps_side_by_side_tables(tmp_path):
    # M-PDF-02: две таблицы на одной Y — обе извлекаются, контент не теряется.
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "sbs.pdf"
    pdf.write_bytes(_side_by_side_tables_pdf())
    res = c._pdf_tables_result(pdf)
    assert res is not None
    assert res.pdf_tables == 2          # обе таблицы, не одна
    # контент обеих таблиц присутствует
    assert "L1" in res.text_content and "aL" in res.text_content
    assert "R1" in res.text_content and "aR" in res.text_content


def test_pdf_tables_result_extracts_ruled_table(tmp_path):
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "ruled.pdf"
    pdf.write_bytes(_ruled_table_pdf_bytes())
    res = c._pdf_tables_result(pdf)
    assert res is not None
    assert res.pdf_tables == 1
    assert "| Name | Value |" in res.text_content
    assert "| alpha | 1 |" in res.text_content
    assert "| beta | 2 |" in res.text_content


def test_convert_file_real_ruled_pdf_end_to_end(tmp_path):
    pytest.importorskip("pdfplumber")
    src = tmp_path / "ruled.pdf"
    src.write_bytes(_ruled_table_pdf_bytes())
    out = tmp_path / "out"
    out.mkdir()
    opts = _pdf_opts(out)
    opts["sandbox"] = False
    assert c.convert_file(src, opts) == "ok"
    body = (out / "ruled.md").read_text(encoding="utf-8")
    assert "pdf_tables: 1" in body
    assert "| Name | Value |" in body
    assert "| alpha | 1 |" in body


def _ruled_pdf_with_cells(rows: list, font_extra: bytes = b"") -> bytes:
    """Разлинованная таблица 2 кол. x 3 стр. с заданным текстом ячеек
    (раскладка как у _ruled_table_pdf_bytes)."""
    content = b""
    for row, y in zip(rows, (705, 685, 665)):
        for text, x in zip(row, (105, 225)):
            content += b"BT /F1 11 Tf %d %d Td (%s) Tj ET\n" % (
                x, y, text.encode("latin-1"))
    content += b"0.5 w\n"
    for x in (100, 220, 340):
        content += b"%d 660 m %d 720 l S\n" % (x, x)
    for y in (720, 700, 680, 660):
        content += b"100 %d m 340 %d l S\n" % (y, y)
    return _wrap_pdf(content, font_extra)


def test_pdf_table_cells_keep_literal_html_characters(tmp_path):
    # Ячейка PDF — литеральный текст: «<script>x</script>» санитизация
    # вырезала целиком, а «List<T>» просмотрщик рендерил как «List».
    pytest.importorskip("pdfplumber")
    src = tmp_path / "cells.pdf"
    src.write_bytes(_ruled_pdf_with_cells([
        ("Name", "Value"),
        ("<script>x</script>", "1"),
        ("List<T>", "A & B &lt;"),
    ]))
    out = tmp_path / "out"
    out.mkdir()
    opts = _pdf_opts(out)
    opts["sandbox"] = False
    assert c.convert_file(src, opts) == "ok"
    body = (out / "cells.md").read_text(encoding="utf-8")
    assert "pdf_tables: 1" in body
    assert "| &lt;script&gt;x&lt;/script&gt; | 1 |" in body
    assert "| List&lt;T&gt; | A & B &amp;lt; |" in body

    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt(
        "commonmark", {"html": True}
    ).enable("table").render(body)
    # После рендеринга видны исходные символы, а не HTML-разметка.
    assert "<td>&lt;script&gt;x&lt;/script&gt;</td>" in html
    assert "<td>List&lt;T&gt;</td>" in html
    assert "<td>A &amp; B &amp;lt;</td>" in html


def test_pdf_table_cells_keep_literal_backticks(tmp_path):
    # «`List<T>`» без экранирования кавычек становился кодом, а в коде
    # сущности не раскрываются: просмотрщик показывал «List&lt;T&gt;».
    # Обратная кавычка в ячейке — литерал; «\» перед ней — тоже.
    pytest.importorskip("pdfplumber")
    src = tmp_path / "ticks.pdf"
    # WinAnsi: в стандартной кодировке Helvetica байт 0x60 — «‘».
    src.write_bytes(_ruled_pdf_with_cells([
        ("Name", "Value"),
        ("`List<T>`", "1"),
        ("x\\\\`y", "2"),  # в PDF-строке «\\» — один «\»
    ], b"/Encoding /WinAnsiEncoding "))
    out = tmp_path / "out"
    out.mkdir()
    opts = _pdf_opts(out)
    opts["sandbox"] = False
    assert c.convert_file(src, opts) == "ok"
    body = (out / "ticks.md").read_text(encoding="utf-8")
    assert "| \\`List&lt;T&gt;\\` | 1 |" in body
    assert "| x\\\\\\`y | 2 |" in body

    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt(
        "commonmark", {"html": True}
    ).enable("table").render(body)
    assert "<td>`List&lt;T&gt;`</td>" in html
    assert "<td>x\\`y</td>" in html


def test_pdf_table_cells_keep_literal_markup(tmp_path):
    # Без кода-в-кавычках ячейка разбиралась как Markdown: «`[x](y)`»
    # давал ссылку, звёздочки и тильды пропадали в курсиве и
    # зачёркивании. Литерал — вся встроенная разметка ячейки.
    pytest.importorskip("pdfplumber")
    src = tmp_path / "markup.pdf"
    src.write_bytes(_ruled_pdf_with_cells([
        ("Name", "Value"),
        ("`[x](y)`", "1"),
        ("a*b* _c_ ~~d~~", "2"),
    ], b"/Encoding /WinAnsiEncoding "))
    out = tmp_path / "out"
    out.mkdir()
    opts = _pdf_opts(out)
    opts["sandbox"] = False
    assert c.convert_file(src, opts) == "ok"
    body = (out / "markup.md").read_text(encoding="utf-8")
    assert "| \\`&#91;x&#93;(y)\\` | 1 |" in body
    assert "| a\\*b\\* \\_c\\_ \\~\\~d\\~\\~ | 2 |" in body

    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt(
        "commonmark", {"html": True}
    ).enable(["table", "strikethrough"]).render(body)
    assert "<td>`[x](y)`</td>" in html
    assert "<td>a*b* _c_ ~~d~~</td>" in html
    assert "<a " not in html and "<em>" not in html and "<s>" not in html


def test_pdf_table_cells_escaped_after_cyrillic_repair(tmp_path, monkeypatch):
    # В сломанном шрифте «>» в ячейке — буква «о»: экранирование до
    # ремонта превратило бы «м>4C;59» в мусор вместо «модулей».
    src = tmp_path / "broken.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()
    body = (
        "НастояIая Методика выявления уя7вимосте9 и "
        "недекларированных во7можносте9 в программном "
        "о1еспеGении.\n"
    ) * 4
    result = c._PdfResult(
        body + "\n| Перечень | м>4C;59 |\n| --- | --- |\n| A | B |\n", 1)
    monkeypatch.setattr(c, "_pdf_tables_result", lambda p: result)
    monkeypatch.setattr(c, "_pdf_page_count", lambda p: 1)
    monkeypatch.setattr(c, "_pdf_text_layer_probe", lambda p: None)

    assert c.convert_file(src, _pdf_opts(out)) == "ok"
    md = (out / "broken.md").read_text(encoding="utf-8")
    assert "| Перечень | модулей |" in md


def test_pdf_text_layer_probe_reads_real_pdf(tmp_path):
    pytest.importorskip("pypdfium2")
    src = tmp_path / "text-layer.pdf"
    src.write_bytes(_ruled_table_pdf_bytes())

    text, page_count = c._pdf_text_layer_probe(src)

    assert page_count == 1
    assert "Name" in text
    assert "alpha" in text


def test_pdf_tables_result_none_for_image_only_pdf(tmp_path):
    pytest.importorskip("pdfplumber")
    from tools.make_image_only_pdf import make_image_only_pdf
    pdf = tmp_path / "scan.pdf"
    make_image_only_pdf(pdf)
    # Нет ни текста, ни таблиц -> None (откат на штатный путь MarkItDown).
    assert c._pdf_tables_result(pdf) is None


# --- псевдографика таблиц (box-drawing) -> GFM ----------------------------

_BOX_TABLE = (
    "Что улучшилось:\n"
    "┌──────────┬──────────┬──────────────┐\n"
    "│ Метрика  │ Режим B  │ Режим C (НКК)│\n"
    "│          │ (SCA/FIM)│              │\n"
    "├──────────┼──────────┼──────────────┤\n"
    "│ Recall   │ ~0,6     │ 0,96         │\n"
    "│ F1       │ ~0,6     │ 0,97         │\n"
    "└──────────┴──────────┴──────────────┘\n"
    "Итог: улучшено."
)


def test_convert_box_tables_to_gfm():
    out = c._convert_box_tables(_BOX_TABLE)
    assert "Что улучшилось:" in out          # проза сверху сохранена
    assert "Итог: улучшено." in out          # проза снизу сохранена
    assert "| Метрика | Режим B (SCA/FIM) | Режим C (НКК) |" in out
    assert "| --- | --- | --- |" in out
    assert "| Recall | ~0,6 | 0,96 |" in out
    assert "| F1 | ~0,6 | 0,97 |" in out
    # символы псевдографики исчезли
    assert not any(ch in out for ch in "│┌┐└┘├┤┬┴┼─")


def test_convert_box_tables_leaves_plain_text():
    txt = "Обычный текст без таблиц.\nВторая строка — с тире."
    assert c._convert_box_tables(txt) == txt


def test_convert_box_tables_leaves_ascii_gfm_untouched():
    gfm = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    # ASCII-пайпы и дефисы не трогаем (ищем только │/┃)
    assert c._convert_box_tables(gfm) == gfm


def test_tidy_converts_box_table():
    out = c.tidy(_BOX_TABLE, keep_images=False)
    assert "| Recall | ~0,6 | 0,96 |" in out
    assert "│" not in out


# --- _row_text сохраняет переносы строк (анти-регрессия «простыни») --------

def test_row_text_preserves_internal_newlines():
    # Многострочная ячейка (абзац, попавший в таблицу) не должна
    # схлопываться в одну строку.
    assert c._row_text(["Строка 1\nСтрока 2\nСтрока 3"]) == \
        "Строка 1\nСтрока 2\nСтрока 3"


# --- чистка PDF-текста: ложные #-заголовки и колонтитулы -------------------

def test_escape_stray_heading_defuses_hash_comment():
    assert c._escape_stray_heading("# /etc/fstab") == "\\# /etc/fstab"
    assert c._escape_stray_heading("## раздел") == "\\## раздел"


def test_escape_stray_heading_leaves_text_and_table_rows():
    assert c._escape_stray_heading("обычный текст") == "обычный текст"
    assert c._escape_stray_heading("| # | x |") == "| # | x |"


def test_clean_pdf_text_escapes_prose_hash_outside_fence():
    # Кириллица с ведущей '#' — это проза-комментарий, не заголовок:
    # экранируем (вне код-блока).
    out = c._clean_pdf_text("# Комментарий\nобычная строка", page_count=1)
    assert "\\# Комментарий" in out
    assert "```" not in out


def test_clean_pdf_text_fences_code_and_keeps_hash_literal():
    # Латинский код-блок (комментарий конфига + UUID) оборачивается в ```,
    # '#' внутри фенса остаётся буквальным (не экранируется).
    out = c._clean_pdf_text(
        "# /etc/fstab static info\nUUID=abc / ext4 defaults 0 1",
        page_count=1,
    )
    assert "```" in out
    assert "# /etc/fstab static info" in out
    assert "\\#" not in out


# --- классификатор и фенсинг кода ------------------------------------------

def test_classify_code_line():
    assert c._classify_code_line("sudo nft add rule") == "code"
    assert c._classify_code_line("CREATE ROLE repl;") == "code"
    assert c._classify_code_line("lsblk -f") == "code"
    assert c._classify_code_line("{<уровень>,<категория>} ;") == "code"
    assert c._classify_code_line("$REPL_PASSWORD") == "code"
    # проза, начинающаяся с пути, — кириллице-доминантна -> НЕ код
    assert c._classify_code_line(
        "/etc/fstab настраивается администратором системы") == "prose"
    assert c._classify_code_line("Обычное предложение на русском.") == "prose"
    assert c._classify_code_line("| a | b |") == "gfm"
    assert c._classify_code_line("’ ’ ’ ’") == "neutral"


def test_fence_code_blocks_groups_runs_and_keeps_prose():
    text = ("Выполнить команду:\n"
            "lsblk -f\n"
            "Вывод команды:\n"
            "NAME FSTYPE UUID\n"
            "vda ext4 44c1\n"
            "Это обычный поясняющий абзац на русском языке.")
    out = c._fence_code_blocks(text)
    assert "```\nlsblk -f\n```" in out
    assert "```\nNAME FSTYPE UUID\nvda ext4 44c1\n```" in out
    assert "Выполнить команду:" in out and "```\nВыполнить" not in out
    assert "Это обычный поясняющий абзац" in out


def test_fence_does_not_touch_real_tables():
    text = "| Параметр | Описание |\n| --- | --- |\n| x | y |"
    assert c._fence_code_blocks(text) == text  # таблица не обёрнута


# --- fence-aware tidy/sanitize (M-PDF-01, L-SAN-03, GAP-01) ----------------

def test_tidy_preserves_dangerous_content_inside_fence():
    # Для базы знаний по ИБ: <script>/javascript:/data: в код-примерах
    # должны сохраняться (фенс-блок рендерится инертно).
    f = "```"
    body = (f + "\n<script>alert(1)</script>\n"
            "[xss](javascript:alert(1))\ndata: app/json\n" + f + "\n")
    out = c.tidy(body, keep_images=False)
    assert "<script>alert(1)</script>" in out
    assert "javascript:alert(1)" in out
    assert "data: app/json" in out


def test_tidy_still_sanitizes_outside_fence():
    # Безопасность сохранена: опасное ВНЕ фенса по-прежнему чистится.
    out = c.tidy("<script>alert(1)</script>\nобычный текст",
                 keep_images=False)
    assert "<script>" not in out


def test_tidy_box_table_not_converted_inside_fence():
    f = "```"
    out = c.tidy(f + "\n│ a │ b │\n" + f + "\n", keep_images=False)
    assert "│ a │ b │" in out  # псевдографика в коде не тронута


# --- FP/FN refinements фенсинга (L-CF-01/02/03) ---------------------------

def test_fence_skips_weak_single_term():
    assert "```" not in c._fence_code_blocks("Python 3.12")
    assert "```" not in c._fence_code_blocks("Nginx")
    assert "```" not in c._fence_code_blocks("https://example.com/path")


def test_fence_keeps_multiline_latin_code():
    out = c._fence_code_blocks("NAME FSTYPE UUID\nvda ext4 44c1")
    assert "```\nNAME FSTYPE UUID\nvda ext4 44c1\n```" in out


def test_fence_russian_comment_continues_code_block():
    out = c._fence_code_blocks(
        "sudo nft add rule\n# настройка порта\nsudo nft list")
    assert out.count("```") == 2          # один общий блок
    assert "# настройка порта" in out


def test_clean_pdf_text_strips_repeated_footer_and_page_numbers():
    pages = []
    for p in range(6):
        pages.append(f"Контент страницы {p}\n"
                     "РУСБ.10015-01 95 01-1\n"  # сквозной колонтитул
                     f"{40 + p}")               # номер страницы
    out = c._clean_pdf_text(c._PDF_PAGE_BREAK.join(pages), page_count=6)
    assert "РУСБ.10015-01 95 01-1" not in out
    assert "\n40\n" not in ("\n" + out + "\n")
    assert "Контент страницы 0" in out
    assert "Контент страницы 5" in out


def test_clean_pdf_text_keeps_unique_doc_and_standalone_number():
    # Нет повторяющегося колонтитула -> одиночное число НЕ срезается
    # (защита документов вроде Предзащиты).
    text = c._PDF_PAGE_BREAK.join(
        ["Параграф один", "Параграф два\n42", "Параграф три"])
    out = c._clean_pdf_text(text, page_count=10)
    assert "42" in out
    assert "Параграф один" in out and "Параграф три" in out


def test_merge_text_blocks_splits_list_items_inside_block():
    """Полоса текста между таблицами приходит одним многострочным
    блоком, и пункты внутри неё слиплись бы так же. Правило про пункты
    применяется к строкам блока, а не только к его границам."""
    blocks = [("text", "Ошибками считаются:\n"
                       "и) переполнение буферов;\n"
                       "к) утечки памяти,\n"
                       "файловых дескрипторов;")]

    out = c._merge_text_blocks(blocks)

    assert out[0][1] == (
        "Ошибками считаются:\n\n"
        "и) переполнение буферов;\n\n"
        "к) утечки памяти,\n"
        "файловых дескрипторов;"
    )


def test_merge_text_blocks_never_loses_content():
    """Инвариант: склейка абзацев и разбивка пунктов только вставляют
    переносы, но НИКОГДА не теряют текст и не переставляют таблицы.

    Правка, которая ввела эти эвристики, была проверена на одном
    документе, поэтому характер риска (молчаливая потеря содержимого)
    закрывается не примером, а свойством на случайных входах."""
    rnd = random.Random(7)
    words = ["система", "защиты", "данных", "требование", "1.6»",
             "тестирование", "модуль", "результат"]
    markers = ["а)", "б)", "1)", "2.", "-", "–", "•", ""]
    table = "| a | b |\n|---|---|\n| 1 | 2 |"

    def squash(bs):
        return re.sub(r"\s+", "", "".join(cnt for _, cnt in bs))

    for _ in range(120):
        blocks = []
        for _ in range(rnd.randint(1, 10)):
            if rnd.random() < 0.25:
                blocks.append(("table", table))
                continue
            rows = []
            for _ in range(rnd.randint(1, 4)):
                body = " ".join(rnd.choice(words)
                                for _ in range(rnd.randint(1, 6)))
                rows.append((rnd.choice(markers) + " " + body).strip())
            blocks.append(("text", "\n".join(rows)))

        out = c._merge_text_blocks(blocks)

        assert squash(out) == squash(blocks)
        assert ([cnt for k, cnt in out if k == "table"]
                == [cnt for k, cnt in blocks if k == "table"])


def test_merge_text_blocks_keeps_list_items_separate():
    """Мягкий перенос Markdown схлопывается в пробел, поэтому склейка
    перечисления в один абзац слила бы пункты в строку. Пункт списка
    начинает новый абзац, а его собственный перенос — нет."""
    blocks = [
        ("text", "Ошибками считаются:"),
        ("text", "и) ненадлежащее обеспечение корректности"),
        ("text", "совместного доступа к данным;"),
        ("text", "к) переполнение буферов;"),
        ("text", "1) первый пункт;"),
        ("text", "– тире-пункт."),
    ]

    out = c._merge_text_blocks(blocks)

    assert len(out) == 1
    assert out[0][1] == (
        "Ошибками считаются:\n\n"
        "и) ненадлежащее обеспечение корректности\n"
        "совместного доступа к данным;\n\n"
        "к) переполнение буферов;\n\n"
        "1) первый пункт;\n\n"
        "– тире-пункт."
    )


def test_merge_text_blocks_joins_consecutive_prose():
    """Соседние текстовые блоки — это перенос строки внутри абзаца, а
    не разные абзацы. Пока их склеивали через пустую строку, каждая
    строка PDF становилась отдельным абзацем Markdown: на реальном
    60-страничном документе 212 из 308 абзацев были однострочными, а
    140 обрывались посреди предложения. Таблицы остаются границами."""
    blocks = [
        ("text", "Должно содержать значение"),
        ("text", "«1.6» или выше."),
        ("table", [["a", "b"]]),
        ("text", "После таблицы"),
        ("text", "продолжение абзаца"),
    ]

    out = c._merge_text_blocks(blocks)

    assert len(out) == 3
    assert out[0] == ("text", "Должно содержать значение\n«1.6» или выше.")
    assert out[1][0] == "table"
    assert out[2] == ("text", "После таблицы\nпродолжение абзаца")


def test_clean_pdf_text_strips_page_numbers_without_footer():
    """Сквозной нумерации без колонтитула раньше хватало, чтобы
    засорить весь вывод: на реальном 60-страничном документе в `.md`
    оставалось 66 голых чисел. Номера убираются, только если идут в
    ногу со страницами, поэтому число, выпадающее из нумерации (ссылка
    на пункт), сохраняется."""
    pages = []
    for p in range(1, 13):
        lines = [f"Содержательный абзац номер {p}"]
        if p == 5:
            lines.append("3")  # ссылка на пункт, назад по счётчику
        lines.append(str(p))
        pages.append("\n".join(lines))
    out = c._clean_pdf_text(c._PDF_PAGE_BREAK.join(pages), page_count=12)
    body = "\n" + out + "\n"

    assert "\n7\n" not in body
    assert "\n12\n" not in body
    assert "\n3\n" in body
    assert "Содержательный абзац номер 7" in out
    assert "Содержательный абзац номер 12" in out


def test_clean_pdf_text_keeps_clustered_numbered_list():
    """Сквозная нумерация идёт ЧЕРЕЗ ВЕСЬ документ, а нумерованный
    перечень сидит в одном месте.

    Без проверки охвата колонка «№» таблицы, разобранной как проза,
    уезжала в мусор целиком: длины цепочки (40 номеров при пороге 30)
    хватало, чтобы принять перечень за пагинацию, и на 60-страничном
    документе молча исчезали все сорок номеров подряд."""
    pages = []
    for p in range(1, 61):
        lines = [f"Абзац {p}.{k} о требованиях к защите данных."
                 for k in range(30)]
        if p == 11:
            for n in range(1, 41):
                lines.append(str(n))
                lines.append(f"Требование номер {n} к средству защиты.")
        pages.append("\n".join(lines))
    out = c._clean_pdf_text(c._PDF_PAGE_BREAK.join(pages), page_count=60)
    body = "\n" + out + "\n"

    missing = [n for n in range(1, 41) if f"\n{n}\n" not in body]
    assert missing == []


def test_strip_pdf_furniture_keeps_list_crossing_pages():
    """Нумерованный перечень, перетекающий через страницы, — не номера
    страниц. Конец перечня внизу страницы и начало вверху следующей
    дают одинаковый сдвиг «значение минус индекс страницы», но стоят в
    разных зонах; пункт «1» в начале первой страницы совпадает по
    сдвигу с номерами страниц, но они внизу. Настоящие номера страниц
    при этом срезаются."""
    pages = []
    for p in range(12):
        lines = []
        for n in range(5 * p + 1, 5 * p + 6):
            lines += [str(n), f"Пункт перечня {n} о мерах защиты."]
        lines.append(str(p + 1))  # номер страницы
        pages.append(lines)

    kept = [ln for page in c._strip_pdf_furniture(pages, 12)
            for ln in page]

    assert [ln for ln in kept if ln.isdigit()] == [
        str(n) for n in range(1, 61)]


def test_strip_pdf_furniture_keeps_number_next_to_page_number():
    """Число того же значения прямо над номером страницы (последняя
    строка таблицы «5» на пятой странице) — содержание: на странице
    срезается только крайний номер зоны."""
    pages = [[f"Строка {k} страницы {p + 1}." for k in range(6)]
             + [str(p + 1)] for p in range(12)]
    pages[4].insert(6, "5")

    kept = c._strip_pdf_furniture(pages, 12)

    assert kept[4][-1] == "5" and len(kept[4]) == 7
    assert all(len(page) == 6 for i, page in enumerate(kept) if i != 4)


def test_strip_pdf_furniture_short_pages_keep_top_number():
    """На короткой странице (слайд) зоны перекрываются, и номер внизу
    попадал бы и в верхнюю зону. Строка относится к ближнему краю,
    поэтому крупное «3» в начале третьего слайда остаётся, а номера
    слайдов внизу срезаются."""
    pages = [[f"Слайд {p + 1}: тема занятия", str(p + 1)]
             for p in range(12)]
    pages[2].insert(0, "3")

    kept = c._strip_pdf_furniture(pages, 12)

    assert kept[2] == ["3", "Слайд 3: тема занятия"]
    assert all(len(page) == 1 for i, page in enumerate(kept) if i != 2)


def test_clean_pdf_text_protects_table_rows():
    text = c._PDF_PAGE_BREAK.join(
        ["FOOT"] * 4 + ["FOOT\n| FOOT | x |\n| --- | --- |"])
    out = c._clean_pdf_text(text, page_count=10)
    assert "| FOOT | x |" in out   # строка таблицы не тронута
    assert "\nFOOT\n" not in ("\n" + out + "\n")  # одиночный колонтитул убран


def test_pdf_images_extracted(tmp_path):
    """PDF со встроенной растровой картинкой → base64 в Markdown."""
    Image = pytest.importorskip("PIL.Image")
    p = tmp_path / "pic.pdf"
    Image.new("RGB", (24, 24), (200, 50, 50)).save(str(p), "PDF")
    md = c._pdf_images_markdown(p)
    assert "data:image/png;base64," in md
    assert "Картинки страницы 1" in md


def test_pdf_images_empty_on_missing(tmp_path):
    """Битый/несуществующий путь → пусто, без исключения."""
    assert c._pdf_images_markdown(tmp_path / "nope.pdf") == ""


class _FakeCropPage:
    """Страница с bbox, не начинающимся в (0,0) — как у сканов ГОСТ.

    pdfplumber поднимает ValueError, если crop-box выходит за bbox
    страницы хоть на сотую пункта.
    """

    bbox = (-0.05, -0.2, 594.95, 841.8)
    width = 595.0
    height = 842.0

    def crop(self, box):
        x0, top, x1, bottom = box
        px0, ptop, px1, pbottom = self.bbox
        if x0 < px0 or top < ptop or x1 > px1 or bottom > pbottom:
            raise ValueError("Bounding box is not fully within parent")
        return SimpleNamespace(
            extract_text=lambda: "текст полосы вне таблицы"
        )


def test_crop_text_survives_offset_page_bbox():
    """Полоса текста не теряется на странице со смещённым bbox.

    На скане ГОСТ Р 34.11-2012 bbox страниц был (-0.05, -0.2, 594.95,
    841.8): crop((0, top, width, bottom)) вылетал за правый край на
    0.05 пункта, ValueError глотался — и ВЕСЬ текст вне принятых
    таблиц молча пропадал (массивы подстановок, формулы, вводные
    предложения). Координаты обязаны клампиться к реальному bbox.
    """
    page = _FakeCropPage()

    got = c._crop_text(page, 0.0, 296.0)

    assert got == "текст полосы вне таблицы"


def test_strip_pdf_furniture_keeps_pure_punctuation_lines():
    """Повторяющаяся строка из одной пунктуации — не колонтитул.

    В Р 71207-2024 строки «}» из примеров кода повторялись чаще
    порога и вырезались как колонтитул — молчаливая потеря кода.
    Настоящий колонтитул (номер документа, версия) всегда содержит
    буквы или цифры.
    """
    pages = []
    for i in range(1, 13):
        pages.append([
            "ГОСТ Р 00000—2024",
            f"int f{i}(void) {{",
            "return 0;",
            "}",
            f"проза страницы {i} о безопасной разработке",
        ])

    kept = [ln for page in c._strip_pdf_furniture(pages, 12)
            for ln in page]

    assert kept.count("}") == 12          # код цел
    assert "ГОСТ Р 00000—2024" not in kept  # колонтитул срезан


# --- колонтитулы по зонам страниц и текст сбоку от таблицы ---------------

def _pages_pdf(contents: list) -> bytes:
    """Многостраничный PDF (A4, Helvetica): по потоку содержимого на
    страницу. Без сторонних библиотек, как `_wrap_pdf`."""
    n = len(contents)
    font = 3 + 2 * n
    kids = b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(n))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n),
    ]
    for i, content in enumerate(contents):
        objs.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 %d 0 R >> >> "
            b"/Contents %d 0 R >>" % (font, 4 + 2 * i))
        objs.append(b"<< /Length %d >>\nstream\n%s\nendstream"
                    % (len(content), content))
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objs) + 1)
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref_pos))
    return out


def _text(x: int, y: int, s: str) -> bytes:
    lit = s.encode().replace(b"(", b"\\(").replace(b")", b"\\)")
    return b"BT /F1 11 Tf %d %d Td (%s) Tj ET\n" % (x, y, lit)


def _ruled_table(top: int) -> bytes:
    """Разлинованная таблица 2x3 (x 100..340), верхний край на `top`."""
    out = [_text(105, top - 15, "Name"), _text(225, top - 15, "Value"),
           _text(105, top - 35, "alpha"), _text(225, top - 35, "1"),
           _text(105, top - 55, "beta"), _text(225, top - 55, "2"),
           b"0.5 w\n"]
    for x in (100, 220, 340):
        out.append(b"%d %d m %d %d l S\n" % (x, top - 60, x, top))
    for y in (top, top - 20, top - 40, top - 60):
        out.append(b"100 %d m 340 %d l S\n" % (y, y))
    return b"".join(out)


def _workbook_pdf(with_table: bool, form_page: bool = False) -> bytes:
    """Восемь страниц: колонтитул сверху и номер страницы снизу (со
    второй страницы). В теле — то, что чистка обязана сохранить:
    «ANSWER: B» на каждой странице (а на третьей ещё и первой строкой
    под колонтитулом), номера строк чек-листа 1..8, одиночное «6» над
    номером страницы и год «2024» на титуле.

    `form_page` добавляет на шестую и седьмую страницы безрамочную
    сетку слов: MarkItDown разбирает их как формы (таблицей) и
    склеивает страницы БЕЗ `\\f`."""
    pages = [_text(200, 500, "Workbook of the final project")
             + _text(200, 480, "Moscow") + _text(200, 460, "2024")]
    for p in range(2, 9):
        lines = [f"Question {p} about the model",
                 f"A) option {p}.1", f"B) option {p}.2", "ANSWER: B",
                 f"Explanation of question {p}", f"Remark {p}",
                 f"Closing text of page {p}"]
        if p == 3:
            lines.insert(0, "ANSWER: B")
        if p == 4:
            lines[4:4] = ["Checklist", "No What How",
                          *map(str, range(1, 9)), "Pass if all rows done"]
        if p == 5:
            lines.append("6")
        body = [_text(72, 800, "DOC-7 Workbook rev 2")]
        body += [_text(72, 760 - 20 * k, s) for k, s in enumerate(lines)]
        body.append(_text(290, 40, str(p)))
        if with_table and p == 2:
            body.append(_ruled_table(320))
        if form_page and p in (6, 7):
            body += [_text(x, 500 - 20 * r, f"{name}{r}")
                     for r in range(8)
                     for x, name in ((72, "Key"), (250, "Val"),
                                     (430, "Unit"))]
        pages.append(b"".join(body))
    return _pages_pdf(pages)


def _bare_numbers(text: str) -> list:
    return [ln.strip() for ln in text.split("\n")
            if re.fullmatch(r"\d{1,4}", ln.strip())]


def test_pdf_tables_result_keeps_repeated_body_lines(tmp_path):
    """Колонтитул — строка в верхней или нижней зоне РАЗНЫХ страниц, а
    не просто частая строка. Прежнее правило считало повторы по всему
    тексту: «ANSWER: B» ×15 в тесте и «Практическое занятие:» ×10 в
    тематическом плане вырезались как колонтитул."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "quiz.pdf"
    pdf.write_bytes(_workbook_pdf(with_table=True))

    res = c._pdf_tables_result(pdf)

    assert res is not None and res.pdf_tables == 1
    text = res.text_content
    assert text.count("ANSWER: B") == 8
    assert "DOC-7 Workbook rev 2" not in text   # колонтитул срезан
    assert "| alpha | 1 |" in text


def test_pdf_tables_result_keeps_body_numbers_and_title_year(tmp_path):
    """Номер страницы режется по положению и последовательности, а не
    «любое отдельное число, раз нашёлся колонтитул»: так пропадали
    номера строк таблицы 1..8 и год «2024» на титуле."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "numbers.pdf"
    pdf.write_bytes(_workbook_pdf(with_table=True))

    text = c._pdf_tables_result(pdf).text_content

    assert "\n1\n2\n3\n4\n5\n6\n7\n8\n" in text   # номера строк целы
    assert "Remark 5\nClosing text of page 5\n6" in text
    assert "2024" in _bare_numbers(text)
    # Кроме них голых чисел нет: номера страниц 2..8 срезаны.
    assert sorted(_bare_numbers(text), key=int) == [
        "1", "2", "3", "4", "5", "6", "6", "7", "8", "2024"]


@pytest.mark.parametrize("form_page", [False, True])
def test_markitdown_fallback_keeps_body_lines_and_numbers(tmp_path,
                                                          form_page):
    """Фолбэк MarkItDown (PDF без таблиц) чистит колонтитулы по тем же
    зонам страниц, что и pdfplumber-путь, — и когда MarkItDown делит
    страницы `\\f` (pdfminer), и когда склеивает их пустой строкой
    (есть страница-форма; как у Р 71207-2024)."""
    pytest.importorskip("pdfplumber")
    src = tmp_path / "plain.pdf"
    src.write_bytes(_workbook_pdf(with_table=False, form_page=form_page))
    out = tmp_path / "out"
    out.mkdir()
    opts = _pdf_opts(out)
    opts["sandbox"] = False

    assert c.convert_file(src, opts) == "ok"

    body = (out / "plain.md").read_text(encoding="utf-8")
    assert body.count("ANSWER: B") == 8
    assert "DOC-7 Workbook rev 2" not in body
    assert sorted(_bare_numbers(body), key=int) == [
        "1", "2", "3", "4", "5", "6", "6", "7", "8", "2024"]
    assert ("| Key0 | Val0 | Unit0 |" in body) is form_page


def test_pdf_tables_result_keeps_text_beside_table(tmp_path):
    """Текст сбоку от таблицы (на её высоте, слева или справа) не
    теряется: раньше извлекались только полосы выше и ниже таблицы на
    всю ширину страницы. Символы самой таблицы в текст не попадают."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "side.pdf"
    pdf.write_bytes(_wrap_pdf(
        _text(72, 780, "Text above the table")
        + _ruled_table(720)
        + _text(20, 685, "LEFT_NOTE")
        + _text(370, 685, "SIDE_NOTE_KEEP")
        + _text(72, 600, "Text below the table")))

    res = c._pdf_tables_result(pdf)

    assert res is not None and res.pdf_tables == 1
    text = res.text_content
    assert "SIDE_NOTE_KEEP" in text
    assert "LEFT_NOTE" in text
    assert "| alpha | 1 |" in text
    assert text.count("alpha") == 1     # таблица не продублирована
    assert text.index("Text above") < text.index("| Name")
    assert text.index("| beta") < text.index("Text below")


def test_pdf_tables_result_side_label_at_table_top_once(tmp_path):
    """Подпись сбоку, пересекающая верхнюю границу таблицы, выводится
    один раз. Полоса над таблицей и полоса от её верха обе захватывали
    символы, задевающие границу (базовая линия 717 при верхней линии
    сетки 720), и подпись дублировалась. Символ относится к одной
    полосе — по середине своей высоты."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "edge.pdf"
    pdf.write_bytes(_wrap_pdf(
        _text(72, 780, "Text above the table")
        + _ruled_table(720)
        + _text(370, 717, "LIMIT 24 mg")
        + _text(72, 600, "Text below the table")))

    text = c._pdf_tables_result(pdf).text_content

    assert text.count("LIMIT 24 mg") == 1
    assert "| alpha | 1 |" in text


def _stepped_table() -> bytes:
    """Ступенчатая таблица: у двух верхних строк две ячейки, у двух
    нижних — только левая; справа от нижних ячеек сетки нет."""
    out = [_text(105, 705, "Name"), _text(225, 705, "Value"),
           _text(105, 685, "alpha"), _text(225, 685, "1"),
           _text(105, 665, "gamma"), _text(105, 645, "delta"),
           b"0.5 w\n100 640 m 100 720 l S\n220 640 m 220 720 l S\n"
           b"340 680 m 340 720 l S\n"]
    for y in (720, 700, 680):
        out.append(b"100 %d m 340 %d l S\n" % (y, y))
    for y in (660, 640):
        out.append(b"100 %d m 220 %d l S\n" % (y, y))
    return b"".join(out)


def test_pdf_tables_result_keeps_text_beside_stepped_table(tmp_path):
    """Текст в прямоугольнике таблицы, но вне её ячеек (справа от
    нижних строк ступенчатой таблицы) не теряется: из прозы убираются
    только символы фактических ячеек, а не всего bbox таблицы."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "stepped.pdf"
    pdf.write_bytes(_wrap_pdf(_stepped_table()
                              + _text(240, 645, "NOTE_OUTSIDE")))

    res = c._pdf_tables_result(pdf)

    assert res is not None and res.pdf_tables == 1
    text = res.text_content
    assert text.count("NOTE_OUTSIDE") == 1
    assert text.count("delta") == 1     # ячейки не продублированы
    assert "| alpha | 1 |" in text


def test_pdf_tables_result_keeps_mixed_size_label_whole(tmp_path):
    """Строка сбоку от таблицы из частей разного кегля на общей базовой
    линии («LIMIT» 11 пт и «24 mg» 10 пт, база 716.9 при верхней линии
    сетки 720) выводится целиком и один раз. По середине символа части
    попадали в разные полосы: «LIMIT», затем таблица, затем «24 mg»."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(_wrap_pdf(
        _ruled_table(720)
        + b"BT /F1 11 Tf 370 716.9 Td (LIMIT ) Tj "
          b"/F1 10 Tf (24 mg) Tj ET\n"))

    text = c._pdf_tables_result(pdf).text_content

    assert "LIMIT 24 mg" in text
    assert text.count("LIMIT") == 1 and text.count("24 mg") == 1


def test_pdf_tables_result_keeps_text_on_offset_mediabox(tmp_path):
    """Страница со смещённым MediaBox [0 -100 595 742]: в координатах
    pdfplumber её низ 942 при высоте 842. Нижняя полоса шла до высоты,
    и подписи у нижнего края (838..849 и целиком ниже 842) терялись."""
    pytest.importorskip("pdfplumber")
    pdf = tmp_path / "offset.pdf"
    pdf.write_bytes(_wrap_pdf(
        _ruled_table(620) + _text(72, -5, "OFFSET LABEL")
        + _text(72, -95, "BOTTOM LABEL"),
        media=b"0 -100 595 742"))

    res = c._pdf_tables_result(pdf)

    assert res is not None and res.pdf_tables == 1
    assert res.text_content.count("OFFSET LABEL") == 1
    assert res.text_content.count("BOTTOM LABEL") == 1


def test_pdfium_fallback_strips_furniture_by_pages(tmp_path, monkeypatch,
                                                   capsys):
    """Текст pypdfium2 (когда MarkItDown вернул мусор) чистится по
    страницам: зонд склеивает их через `_PDF_PAGE_BREAK`, и
    `_clean_pdf_text` видит границы страниц."""
    pytest.importorskip("pypdfium2")
    src = tmp_path / "pdfium.pdf"
    src.write_bytes(_workbook_pdf(with_table=False))
    out = tmp_path / "out"
    out.mkdir()
    garbage = SimpleNamespace(text_content="??", title=None)
    monkeypatch.setattr(c, "_convert_file_data", lambda p: (garbage, None))
    opts = _pdf_opts(out)
    opts["sandbox"] = False

    assert c.convert_file(src, opts) == "ok"

    assert "text via pypdfium2" in capsys.readouterr().out
    body = (out / "pdfium.md").read_text(encoding="utf-8")
    assert body.count("ANSWER: B") == 8
    assert "DOC-7 Workbook rev 2" not in body
    assert sorted(_bare_numbers(body), key=int) == [
        "1", "2", "3", "4", "5", "6", "6", "7", "8", "2024"]


def test_markitdown_formfeed_pages_use_real_page_count(tmp_path):
    """Число страниц на ветке `\f` — не число `\f`.

    В выводе MarkItDown (pdfminer) на 12 страниц приходится 11 `\f`.
    Порог по ним был бы max(5, 11 // 2) = 5 вместо 6, и строка вверху
    ровно пяти страниц из двенадцати срезалась бы как колонтитул."""
    pages = [f"Раздел {p}. Требования к средствам защиты." for p in range(12)]
    for p in (0, 3, 6, 8, 10):
        pages[p] = "Повторяющаяся строка раздела\n" + pages[p]
    text = "\f".join(pages)

    out = c._strip_markitdown_furniture(text, tmp_path / "absent.pdf")

    assert out.count("Повторяющаяся строка раздела") == 5
