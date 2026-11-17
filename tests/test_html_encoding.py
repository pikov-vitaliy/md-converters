import sys
from types import SimpleNamespace

import convert_to_md


def test_decode_short_cp1251_html_without_meta():
    raw = "<html><body><h1>Привет</h1><p>текст</p></body></html>".encode(
        "cp1251"
    )

    text, encoding = convert_to_md.decode_html_bytes(raw)

    assert "Привет" in text
    assert "текст" in text
    assert encoding == "cp1251"


def test_decode_cp1251_html_with_meta():
    raw = (
        '<html><head><meta charset="windows-1251"></head>'
        "<body>Отчёт</body></html>"
    ).encode("cp1251")

    text, encoding = convert_to_md.decode_html_bytes(raw)

    assert "Отчёт" in text
    assert encoding == "windows-1251"


def test_decode_koi8r_html_without_meta():
    raw = "<html><body>Привет</body></html>".encode("koi8-r")

    text, encoding = convert_to_md.decode_html_bytes(raw)

    assert "Привет" in text
    assert encoding == "koi8-r"


def test_decode_utf8_bom_html():
    raw = b"\xef\xbb\xbf" + "<html><body>Привет</body></html>".encode(
        "utf-8"
    )

    text, encoding = convert_to_md.decode_html_bytes(raw)

    assert text.startswith("<html>")
    assert "Привет" in text
    assert encoding == "utf-8-sig"


def test_decode_utf32_le_bom_not_mistaken_for_utf16():
    # UTF-32-LE начинается с \xff\xfe, как и UTF-16-LE; должен опознаться
    # как utf-32 и декодироваться без мусора.
    raw = "<html><body>Привет</body></html>".encode("utf-32")

    text, encoding = convert_to_md.decode_html_bytes(raw)

    assert "Привет" in text
    assert encoding == "utf-32"


def test_decode_fallback_reports_replacement(monkeypatch):
    class EmptyDetector:
        def best(self):
            return None

    monkeypatch.setattr(
        convert_to_md,
        "_best_cyrillic_decode",
        lambda raw: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "charset_normalizer",
        SimpleNamespace(from_bytes=lambda raw: EmptyDetector()),
    )

    text, encoding = convert_to_md.decode_html_bytes(b"\xff\xfe\x00")

    assert text
    assert encoding == "cp1251-replace"


def test_decode_http_charset_beats_meta_but_not_bom():
    # HTML-стандарт: BOM, затем кодировка из Content-Type, затем <meta>.
    page = '<html><head><meta charset="koi8-r"></head><body>Отчёт</body>'
    raw = page.encode("cp1251")

    text, encoding = convert_to_md.decode_html_bytes(
        raw, http_charset="windows-1251")

    assert "Отчёт" in text
    assert encoding == "windows-1251"

    bom = b"\xef\xbb\xbf" + page.encode("utf-8")
    text, encoding = convert_to_md.decode_html_bytes(
        bom, http_charset="windows-1251")

    assert "Отчёт" in text
    assert encoding == "utf-8-sig"


def test_decode_html_labels_follow_whatwg():
    # Для HTML «iso-8859-1» и «latin1» — это windows-1252 (WHATWG, так
    # читают браузеры): иначе «€» и “кавычки” становились U+0080/U+0093.
    page = "<p>20 €, “yes”</p>"
    raw = page.encode("cp1252")

    text, encoding = convert_to_md.decode_html_bytes(
        raw, http_charset="ISO-8859-1")
    assert text == page and encoding == "windows-1252"

    meta = b'<meta charset="latin1">' + raw
    text, encoding = convert_to_md.decode_html_bytes(meta)
    assert text.endswith(page) and encoding == "windows-1252"

    # Незанятый байт 0x81 — управляющий U+0081, как в браузере, а не
    # повод уйти в угадывание кодировки.
    text, encoding = convert_to_md.decode_html_bytes(
        raw + b"\x81", http_charset="iso-8859-1")
    assert text == page + "\x81" and encoding == "windows-1252"
