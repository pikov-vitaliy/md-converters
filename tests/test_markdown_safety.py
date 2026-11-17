from types import SimpleNamespace

import pytest

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


# --- b2: текст не вычищается, а экранируется; код и данные не трогаются ---

def test_tidy_escapes_dangerous_tags_in_prose_instead_of_deleting():
    # Строка со слайда реальной презентации: «<script>» исчезал, хотя
    # это текст документа, а не разметка.
    text = (
        "- [ ] тесты: <script>, onclick - вычищаются\n\n"
        "Пример: <script>alert(1)</script> и <iframe src=x></iframe>\n"
    )

    out = convert_to_md.tidy(text, keep_images=False)

    assert "<script" not in out and "<iframe" not in out
    assert "тесты: &lt;script&gt;, onclick - вычищаются" in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt("commonmark", {"html": True}).render(out)
    assert "<script" not in html and "<iframe" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_tidy_keeps_fenced_code_with_language_and_tildes():
    text = (
        "```html\n<script>KEEP_1</script>\n```\n\n"
        "~~~\n<iframe src=javascript:KEEP_2></iframe>\n~~~\n\n"
        "````md\n```\n<script>KEEP_3</script>\n```\n````\n\n"
        "<script>OUT</script>\n"
    )

    out = convert_to_md.tidy(text, keep_images=False)

    assert "<script>KEEP_1</script>" in out
    assert "<iframe src=javascript:KEEP_2></iframe>" in out
    # Внутренняя ``` не закрывает внешнюю ````: содержимое — код.
    assert "<script>KEEP_3</script>" in out
    # После закрытой ограды проза снова под санитизацией.
    assert "&lt;script&gt;OUT&lt;/script&gt;" in out


def test_tidy_keeps_inline_code():
    text = (
        "Пример `<script>KEEP</script>` и ``a ` <iframe>b`` в тексте,\n"
        "ссылка `[y](javascript:alert(2))` тоже код.\n"
    )

    assert convert_to_md.tidy(text, keep_images=False) == text


def test_tidy_code_markers_inside_live_html_are_not_code():
    # Обратная кавычка в атрибуте не открывает код: CommonMark разбирает
    # тег раньше. И в сыром HTML-блоке Markdown не действует — ни
    # кавычки, ни ограда там не делают код, `<script>` живой. Блок
    # <pre> идёт последним: по CommonMark он кончается на строке с
    # </script>, и вторая ``` открывает ограду до конца текста.
    text = (
        'текст <a title="`" onclick="alert(1)" x="`">x</a>\n\n'
        "<div>\n`<script>alert(2)</script>`\n</div>\n\n"
        "\\`<script>alert(4)</script>\\`\n\n"
        "<pre>\n\n```\n<script>alert(3)</script>\n```\n</pre>\n"
    )

    out = convert_to_md.tidy(text, keep_images=False)

    assert "onclick" not in out
    assert "<script" not in out


def test_convert_json_and_xml_are_fenced_data(tmp_path):
    # «"data:field"» превращался в «blocked», «<script>» внутри строки
    # вырезался: JSON и XML — данные, их место в ограде кода. Ограда
    # длиннее ``` внутри значения, иначе данные закрыли бы её.
    data = ('{"data:field":"KEEP_ME", '
            '"example":"<script>TEXT</script>", "md": "```"}')
    (tmp_path / "values.json").write_text(data, encoding="utf-8")
    xml = '<root><a href="javascript:x">v</a><script>T</script></root>'
    (tmp_path / "markup.xml").write_text(xml, encoding="utf-8")
    rss = ('<?xml version="1.0"?><rss version="2.0"><channel>'
           "<title>Лента</title><item><title>Новость</title>"
           "</item></channel></rss>")
    (tmp_path / "feed.xml").write_text(rss, encoding="utf-8")
    out = tmp_path / "out"
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "sandbox": False,
        "scan": {".json", ".xml"}, "tool": "tomd", "planned": set(),
    }

    for name in ("values.json", "markup.xml", "feed.xml"):
        assert convert_to_md.convert_file(tmp_path / name, opts) == "ok"

    def body(stem):
        return (out / f"{stem}.md").read_text(encoding="utf-8")

    assert body("values") == f"````json\n{data}\n````\n"
    assert body("markup") == f"```xml\n{xml}\n```\n"
    # RSS MarkItDown уже разобрал в Markdown — его не огораживаем.
    assert "```" not in body("feed") and "# Лента" in body("feed")
