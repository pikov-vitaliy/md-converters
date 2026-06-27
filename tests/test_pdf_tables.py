"""PDF-таблицы через pdfplumber: чистые функции обработки строк, склейка
переносных таблиц, поле front-matter, флаг --pdf-tables и интеграция в
convert_file. Большинство тестов — на списках строк и мок-результатах
(как в test_pdf_text_layer); плюс несколько на реальном zero-dep PDF,
чтобы покрыть саму pdfplumber-glue (find_tables/bbox/extract)."""
from types import SimpleNamespace

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

def _wrap_pdf(content: bytes) -> bytes:
    """Оборачивает поток содержимого в минимальный валидный PDF (1 стр.,
    шрифт Helvetica). Используется для side-by-side фикстуры."""
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
    lines = []
    for p in range(6):
        lines.append(f"Контент страницы {p}")
        lines.append("РУСБ.10015-01 95 01-1")  # сквозной колонтитул
        lines.append(str(40 + p))              # номер страницы
    out = c._clean_pdf_text("\n".join(lines), page_count=6)
    assert "РУСБ.10015-01 95 01-1" not in out
    assert "\n40\n" not in ("\n" + out + "\n")
    assert "Контент страницы 0" in out
    assert "Контент страницы 5" in out


def test_clean_pdf_text_keeps_unique_doc_and_standalone_number():
    # Нет повторяющегося колонтитула -> одиночное число НЕ срезается
    # (защита документов вроде Предзащиты).
    text = "Параграф один\nПараграф два\n42\nПараграф три"
    out = c._clean_pdf_text(text, page_count=10)
    assert "42" in out
    assert "Параграф один" in out and "Параграф три" in out


def test_clean_pdf_text_protects_table_rows():
    text = "FOOT\nFOOT\nFOOT\nFOOT\nFOOT\n| FOOT | x |\n| --- | --- |"
    out = c._clean_pdf_text(text, page_count=10)
    assert "| FOOT | x |" in out   # строка таблицы не тронута
    assert "\nFOOT\n" not in ("\n" + out + "\n")  # одиночный колонтитул убран
