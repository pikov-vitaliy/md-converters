"""Карта шрифта PDF по контурам глифов (_pdf_glyph_fixed_copy).

Синтетика: свой TrueType-шрифт из трёх букв («м», «и», «р») с разными
контурами и PDF, где ToUnicode намеренно неверна (буквы извлекаются
управляющими символами, как прописные в Методике ФСТЭК России 2026 г.).
Шрифт «установлен» через MD_CONVERTERS_FONT_DIRS.
"""
import zlib

import pdfplumber
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

import convert_to_md as c

LETTERS = {"uni043C": 0x043C, "uni0438": 0x0438, "uni0440": 0x0440}
WORD = [1, 2, 3] * 6  # «мирмир…», CID = GID


def _font_bytes(family="MdcTestSerif", glyphs=None):
    """glyphs: [(имя глифа, код Unicode, номер формы)]; одинаковый номер
    формы — одинаковый контур (двойники вроде латинской A и русской А)."""
    if glyphs is None:
        glyphs = [(n, cp, i) for i, (n, cp) in enumerate(LETTERS.items(), 1)]
    order = [".notdef"] + [g[0] for g in glyphs]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({cp: n for n, cp, _ in glyphs})
    shapes = {".notdef": 0}
    shapes.update({n: k for n, _, k in glyphs})
    outlines = {}
    for name in order:
        pen = TTGlyphPen(None)
        k = shapes[name]
        if k:  # у каждой формы свой прямоугольник — свой контур
            pen.moveTo((50, 0))
            pen.lineTo((50, 200 + 100 * k))
            pen.lineTo((400 + 50 * k, 200 + 100 * k))
            pen.lineTo((400 + 50 * k, 0))
            pen.closePath()
        outlines[name] = pen.glyph()
    fb.setupGlyf(outlines)
    fb.setupHorizontalMetrics({n: (600, 50) for n in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    import io
    buf = io.BytesIO()
    fb.save(buf)
    return buf.getvalue()


def _tounicode(mapping):
    body = "\n".join(f"<{cid:04X}> <{ord(ch):04X}>"
                     for cid, ch in mapping.items())
    return (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /T def /CMapType 2 def\n"
        "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
        f"{len(mapping)} beginbfchar\n{body}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end"
    ).encode("ascii")


def _pdf(path, font, tounicode, encoding=b"/Identity-H", cids=None,
         extra=()):
    text = "".join(f"{cid:04X}" for cid in (cids or WORD))
    content = f"BT /F1 24 Tf 72 700 Td <{text}> Tj ET".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+MdcTestSerif "
        b"/Encoding " + encoding + b" /DescendantFonts [6 0 R] "
        b"/ToUnicode 8 0 R >>",
        None,  # 5: содержимое
        b"<< /Type /Font /Subtype /CIDFontType2 "
        b"/BaseFont /ABCDEF+MdcTestSerif /CIDToGIDMap /Identity "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) "
        b"/Supplement 0 >> /FontDescriptor 7 0 R /DW 600 >>",
        b"<< /Type /FontDescriptor /FontName /ABCDEF+MdcTestSerif "
        b"/Flags 32 /FontBBox [0 -200 1000 800] /ItalicAngle 0 "
        b"/Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 "
        b"/FontFile2 9 0 R >>",
        None,  # 8: ToUnicode
        None,  # 9: шрифт
        *extra,  # 10…: доп. объекты теста
    ]
    streams = {5: content, 8: tounicode, 9: zlib.compress(font)}
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, obj in enumerate(objs, 1):
        offsets.append(len(out))
        if num in streams:
            data = streams[num]
            extra = b" /Filter /FlateDecode" if num == 9 else b""
            if num == 9:
                extra += b" /Length1 %d" % len(font)
            obj = (b"<< /Length %d%s >>\nstream\n" % (len(data), extra)
                   + data + b"\nendstream")
        out += b"%d 0 obj\n" % num + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref))
    path.write_bytes(bytes(out))
    return path


BROKEN = {1: "\x14", 2: "\x15", 3: "\x16"}
RIGHT = {1: "м", 2: "и", 3: "р"}


def _text(path):
    with pdfplumber.open(path) as pdf:
        return pdf.pages[0].extract_text() or ""


@pytest.fixture
def fonts(tmp_path, monkeypatch):
    folder = tmp_path / "шрифты системы"
    folder.mkdir()
    (folder / "mdc-test.ttf").write_bytes(_font_bytes())
    monkeypatch.setenv("MD_CONVERTERS_FONT_DIRS", str(folder))
    monkeypatch.setattr(c, "_SYSTEM_FONTS", None)
    return folder


def test_broken_tounicode_fixed_by_glyph_outlines(tmp_path, fonts):
    src = _pdf(tmp_path / "битая карта.pdf", _font_bytes(),
               _tounicode(BROKEN))
    assert "мир" not in _text(src)
    fixed = c._pdf_glyph_fixed_copy(src)
    assert fixed is not None
    path, count = fixed
    try:
        assert count == 3
        assert "мирмир" in _text(path)
    finally:
        import shutil
        shutil.rmtree(path.parent, ignore_errors=True)


def test_convert_file_reads_fixed_copy(tmp_path, fonts, monkeypatch):
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN))
    out = tmp_path / "out"
    out.mkdir()
    made = []

    def mkdtemp(prefix=""):
        made.append(tmp_path / f"{prefix}{len(made)}")
        made[-1].mkdir()
        return str(made[-1])

    monkeypatch.setattr(c.tempfile, "mkdtemp", mkdtemp)
    opts = {
        "force": True, "frontmatter": True, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "scan": {".pdf"},
        "tool": "tomd", "planned": set(), "pdf_tables": "auto",
    }
    assert c.convert_file(src, opts) == "ok"
    md = (out / "doc.md").read_text("utf-8")
    assert "мирмир" in md
    assert src.read_bytes().startswith(b"%PDF-1.4")  # исходник не тронут
    assert made and not any(p.exists() for p in made)  # копия убрана


def test_font_not_installed_leaves_pdf_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("MD_CONVERTERS_FONT_DIRS", str(tmp_path / "нет"))
    monkeypatch.setattr(c, "_SYSTEM_FONTS", {})
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN))
    assert c._pdf_glyph_fixed_copy(src) is None


def test_correct_map_not_rewritten(tmp_path, fonts, monkeypatch):
    # Проба пропустила бы и так; заставляем сравнить карты напрямую.
    monkeypatch.setattr(c, "_pdf_glyph_fix_needed", lambda path: True)
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(RIGHT))
    assert c._pdf_glyph_fixed_copy(src) is None


def test_other_family_installed_is_not_used(tmp_path, monkeypatch):
    # Шрифт с тем же контуром, но другим именем — не повод переписывать.
    folder = tmp_path / "fonts"
    folder.mkdir()
    (folder / "x.ttf").write_bytes(_font_bytes("OtherSans"))
    monkeypatch.setenv("MD_CONVERTERS_FONT_DIRS", str(folder))
    monkeypatch.setattr(c, "_SYSTEM_FONTS", None)
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN))
    assert c._pdf_glyph_fixed_copy(src) is None


def _install(tmp_path, monkeypatch, font):
    folder = tmp_path / "fonts"
    folder.mkdir()
    (folder / "sys.ttf").write_bytes(font)
    monkeypatch.setenv("MD_CONVERTERS_FONT_DIRS", str(folder))
    monkeypatch.setattr(c, "_SYSTEM_FONTS", None)
    monkeypatch.setattr(c, "_pdf_glyph_fix_needed", lambda path: True)


# Ревью Codex (круг E): три способа испортить ИСПРАВНЫЙ PDF.

def test_same_gid_other_letter_does_not_replace(tmp_path, monkeypatch):
    # Латинские ABC и русские АВС одной формы; в системном шрифте на
    # номерах 1-3 латиница, во встроенном — кириллица. Верная карта
    # (кириллица) не должна смениться латиницей.
    latin = [("A", 0x41, 1), ("B", 0x42, 2), ("C", 0x43, 3)]
    cyr = [("uni0410", 0x410, 1), ("uni0412", 0x412, 2),
           ("uni0421", 0x421, 3)]
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=latin + cyr))
    src = _pdf(tmp_path / "doc.pdf",
               _no_cmap(_font_bytes(glyphs=cyr + latin)),
               _tounicode({1: "А", 2: "В", 3: "С"}))
    assert c._pdf_glyph_fixed_copy(src) is None


def test_non_identity_encoding_left_alone(tmp_path, monkeypatch):
    # Коды ToUnicode равны CID только при Identity-H/V.
    _install(tmp_path, monkeypatch, _font_bytes())
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN),
               encoding=b"/UniGB-UCS2-H")
    assert c._pdf_glyph_fixed_copy(src) is None


def test_ligature_expansions_kept(tmp_path, monkeypatch):
    # Верное раскрытие «ffi» для глифа ﬃ — не ошибка карты.
    ligs = [("uniFB03", 0xFB03, 1), ("uniFB01", 0xFB01, 2),
            ("uniFB00", 0xFB00, 3)]
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=ligs))
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=ligs),
               _tounicode_multi({1: "ffi", 2: "fi", 3: "ff"}))
    assert c._pdf_glyph_fixed_copy(src) is None


def test_failed_write_leaves_no_temp(tmp_path, fonts, monkeypatch):
    import pypdf
    made = []

    def mkdtemp(prefix=""):
        made.append(tmp_path / f"{prefix}{len(made)}")
        made[-1].mkdir()
        return str(made[-1])

    def broken_write(self, stream):
        stream.write(b"%PDF-")
        raise OSError("диск заполнен")

    monkeypatch.setattr(c.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(pypdf.PdfWriter, "write", broken_write)
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN))
    assert c._pdf_glyph_fixed_copy(src) is None
    assert made and not any(p.exists() for p in made)


def _tounicode_multi(mapping):
    body = "\n".join(
        f"<{cid:04X}> <{text.encode('utf-16-be').hex().upper()}>"
        for cid, text in mapping.items())
    return (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CMapName /T def /CMapType 2 def\n"
        "1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
        f"{len(mapping)} beginbfchar\n{body}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end"
    ).encode("ascii")


def _no_cmap(font_bytes):
    """Подмножество шрифта в PDF обычно без своей Unicode-карты."""
    import io

    from fontTools.ttLib import TTFont
    font = TTFont(io.BytesIO(font_bytes))
    del font["cmap"]
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def _fixed_text(src):
    fixed = c._pdf_glyph_fixed_copy(src)
    assert fixed is not None
    path, _count = fixed
    try:
        return _text(path)
    finally:
        import shutil
        shutil.rmtree(path.parent, ignore_errors=True)


MIR = [("uni043C", 0x43C, 4), ("uni0438", 0x438, 5), ("uni0440", 0x440, 6)]


# Ревью Codex (круг E2): выбор одной буквы среди двойников по контуру.

def test_indirect_identity_encoding_still_fixed(tmp_path, fonts):
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode(BROKEN),
               encoding=b"10 0 R", extra=[b"/Identity-H"])
    assert "мирмир" in _fixed_text(src)


def test_embedded_cmap_picks_twin_for_broken_values(tmp_path, monkeypatch):
    # Битая карта даёт управляющие символы для глифов русских АВС (их
    # контур совпадает с латинскими ABC). Выбор среди двойников делает
    # собственная карта встроенного шрифта: кириллица.
    latin = [("A", 0x41, 1), ("B", 0x42, 2), ("C", 0x43, 3)]
    cyr = [("uni0410", 0x410, 1), ("uni0412", 0x412, 2),
           ("uni0421", 0x421, 3)]
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=latin + cyr + MIR))
    broken = {1: "\x11", 2: "\x12", 3: "\x13", 4: "\x14", 5: "\x15",
              6: "\x16"}
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=cyr + MIR + latin),
               _tounicode(broken), cids=[1, 2, 3, 4, 5, 6] * 3)
    text = _fixed_text(src)
    assert "АВСмир" in text and "ABC" not in text

def test_same_gid_breaks_tie_between_twins(tmp_path, monkeypatch):
    # ‒ (U+2012) и – (U+2013) одного контура; подмножество без своей
    # карты, номера глифов сохранены. Нужен знак с того же номера.
    glyphs = [("figuredash", 0x2012, 1), ("endash", 0x2013, 1)] + MIR
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=glyphs))
    broken = {2: "3", 3: "\x14", 4: "\x15", 5: "\x16"}
    src = _pdf(tmp_path / "doc.pdf", _no_cmap(_font_bytes(glyphs=glyphs)),
               _tounicode(broken), cids=[3, 4, 5, 2] * 4)
    text = _fixed_text(src)
    assert "мир–" in text and "‒" not in text


def test_multichar_values_kept(tmp_path, monkeypatch):
    # «1/2» для глифа ½ — сознательное раскрытие: поиск «1/2» должен
    # находить значение и после ремонта соседних букв.
    glyphs = [("onehalf", 0xBD, 1)] + MIR
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=glyphs))
    mapping = {1: "1/2", 2: "\x14", 3: "\x15", 4: "\x16"}
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=glyphs),
               _tounicode_multi(mapping), cids=[1, 2, 3, 4] * 4)
    text = _fixed_text(src)
    assert "1/2мир" in text and "½" not in text




# Ревью Codex (круг E3): меняется только то, что контур опровергает.

def test_empty_value_does_not_abort_repair(tmp_path, monkeypatch):
    # У четвёртого глифа (в тексте не используется) значение карты
    # пустое; раньше ord("") ронял ремонт всего шрифта.
    glyphs = [(n, cp, i) for i, (n, cp) in enumerate(LETTERS.items(), 1)]
    glyphs.append(("uni0430", 0x430, 7))
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=glyphs))
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=glyphs),
               _tounicode_multi({**BROKEN, 4: ""}))
    assert "мирмир" in _fixed_text(src)

def test_control_sequences_are_repaired(tmp_path, fonts):
    broken = {1: "\x14\x15", 2: "\x15\x16", 3: "\x16\x17"}
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(), _tounicode_multi(broken))
    assert "мирмир" in _fixed_text(src)


def test_confirmed_letters_kept_despite_own_cmap(tmp_path, monkeypatch):
    # Своя карта подмножества даёт символы частного использования, а
    # верная ToUnicode — русские А, О, Е, подтверждённые контуром.
    latin = [("A", 0x41, 1), ("O", 0x4F, 2), ("E", 0x45, 3)]
    cyr = [("uni0410", 0x410, 1), ("uni041E", 0x41E, 2),
           ("uni0415", 0x415, 3)]
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=latin + cyr + MIR))
    pua = [("uni0410", 0xE001, 1), ("uni041E", 0xE002, 2),
           ("uni0415", 0xE003, 3)]
    mapping = {1: "А", 2: "О", 3: "Е", 4: "\x14", 5: "\x15", 6: "\x16"}
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=pua + MIR),
               _tounicode(mapping), cids=[1, 2, 3, 4, 5, 6] * 3)
    text = _fixed_text(src)
    assert "АОЕмир" in text and "\ue001" not in text


def test_nfkc_equivalent_values_kept(tmp_path, monkeypatch):
    # «1» для надстрочной ¹ — верное текстовое значение: поиск «1»
    # должен находить его и после ремонта соседних букв.
    glyphs = [("onesuperior", 0xB9, 7)] + MIR
    _install(tmp_path, monkeypatch, _font_bytes(glyphs=glyphs))
    mapping = {1: "1", 2: "\x14", 3: "\x15", 4: "\x16"}
    src = _pdf(tmp_path / "doc.pdf", _font_bytes(glyphs=glyphs),
               _tounicode(mapping), cids=[1, 2, 3, 4] * 4)
    text = _fixed_text(src)
    assert "1мир" in text and "¹" not in text
