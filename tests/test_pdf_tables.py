"""PDF-таблицы через pdfplumber: чистые функции обработки строк, склейка
переносных таблиц, поле front-matter, флаг --pdf-tables и интеграция в
convert_file. Реальные PDF не нужны — тестируем логику на списках строк
и мок-результатах (как в test_pdf_text_layer)."""
from types import SimpleNamespace

import convert_to_md as c


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
