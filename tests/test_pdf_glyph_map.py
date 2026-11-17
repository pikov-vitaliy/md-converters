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


def _font_bytes(family="MdcTestSerif"):
    order = [".notdef"] + list(LETTERS)
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(dict((cp, n) for n, cp in LETTERS.items()))
    glyphs = {}
    for i, name in enumerate(order):
        pen = TTGlyphPen(None)
        if i:  # у каждой буквы свой прямоугольник — свой контур
            pen.moveTo((50, 0))
            pen.lineTo((50, 200 + 100 * i))
            pen.lineTo((400 + 50 * i, 200 + 100 * i))
            pen.lineTo((400 + 50 * i, 0))
            pen.closePath()
        glyphs[name] = pen.glyph()
    fb.setupGlyf(glyphs)
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


def _pdf(path, font, tounicode):
    text = "".join(f"{cid:04X}" for cid in WORD)
    content = f"BT /F1 24 Tf 72 700 Td <{text}> Tj ET".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /ABCDEF+MdcTestSerif "
        b"/Encoding /Identity-H /DescendantFonts [6 0 R] "
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
