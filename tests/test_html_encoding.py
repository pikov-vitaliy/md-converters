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
