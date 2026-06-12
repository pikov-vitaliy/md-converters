from types import SimpleNamespace

import convert_to_md


def test_sanitize_markdown_blocks_dangerous_link_schemes():
    text = (
        "[x](javascript:alert(1)) "
        "![a](vbscript:msgbox(1)) "
        "[local](file:///c:/secret.txt) "
        "[data](data:text/html;base64,PHNjcmlwdD4=)"
    )

    out = convert_to_md.sanitize_markdown(text, keep_images=False)

    lowered = out.lower()
    assert "javascript:" not in lowered
    assert "vbscript:" not in lowered
    assert "file:" not in lowered
    assert "data:text/html" not in lowered


def test_sanitize_markdown_escapes_malicious_image_label():
    text = "![x](javascript:alert(1))](data:image/png;base64,AAAA)"

    out = convert_to_md.sanitize_markdown(text, keep_images=False)

    assert "javascript:" not in out.lower()
    assert "data:image" not in out.lower()
    assert "](data:" not in out.lower()


def test_sanitize_markdown_removes_raw_html_handlers():
    text = (
        '<a href="javascript:alert(1)" onclick="alert(2)">x</a>'
        '<script>alert(3)</script>'
        '<img src="file:///c:/secret.txt" onerror="alert(4)">'
    )

    out = convert_to_md.sanitize_markdown(text, keep_images=False)

    lowered = out.lower()
    assert "javascript:" not in lowered
    assert "onclick" not in lowered
    assert "<script" not in lowered
    assert "file:" not in lowered
    assert "onerror" not in lowered


def test_emit_sanitizes_by_default(tmp_path):
    target = tmp_path / "out.md"
    result = SimpleNamespace(
        text_content="![x](javascript:alert(1))](data:image/png;base64,AAAA)",
        title=None,
    )

    convert_to_md._emit(
        target,
        result,
        "evil.html",
        frontmatter=False,
        keep_images=False,
        tool="tomd",
        note=None,
    )

    out = target.read_text(encoding="utf-8").lower()
    assert "javascript:" not in out
    assert "data:image" not in out


def test_emit_can_preserve_raw_markdown_when_explicit(tmp_path):
    target = tmp_path / "out.md"
    result = SimpleNamespace(
        text_content="[x](javascript:alert(1))",
        title=None,
    )

    convert_to_md._emit(
        target,
        result,
        "trusted.html",
        frontmatter=False,
        keep_images=False,
        tool="tomd",
        note=None,
        safe_markdown=False,
    )

    out = target.read_text(encoding="utf-8").lower()
    assert "javascript:" in out


def test_safe_data_image_requires_strict_base64_when_images_kept():
    text = (
        "![ok](data:image/png;base64,QUJDRA==)\n"
        "![bad](data:image/png;base64,QUJD RA==)\n"
    )

    out = convert_to_md.sanitize_markdown(text, keep_images=True)

    assert "QUJDRA==" in out
    assert "QUJD RA==" not in out
