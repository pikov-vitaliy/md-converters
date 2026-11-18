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


@pytest.mark.parametrize("text", [
    # Обратная кавычка в атрибуте не открывает код: тег разбирается
    # раньше, и обработчик живой.
    'текст <a title="`" onclick="alert(1)" x="`">x</a>',
    # В сыром HTML-блоке Markdown не действует — ни кавычки, ни ограда
    # кодом не становятся; в том числе внутри цитаты и пункта списка.
    "<div>\n`<script>alert(2)</script>`\n</div>",
    "<pre>\n\n```\n<script>alert(3)</script>\n```\n</pre>",
    "> <div>\n> `<script>alert(4)</script>`",
    "- <div>\n  `<script>alert(5)</script>`",
    # Экранированная кавычка — литерал, код она не открывает.
    "\\`<script>alert(6)</script>`",
    # Встроенный код не переходит границу блока и ячейки таблицы.
    "# Заголовок `x\nтекст <script>alert(7)</script>` y",
    "| h1 | h2 |\n| --- | --- |\n| `a | <script>alert(8)</script> b` |",
    # Отступ 4+ без пустой строки перед ним — продолжение абзаца, а
    # строка левее такой ограды уже вне пункта списка.
    "абзац\n    ```\n    <script>alert(9)</script>",
    "    ```\nтекст <script>alert(10)</script>\n    ```",
    "- a\n\n    ```\n    x\n<script>alert(11)</script>\n    ```",
    # Ограда с отступом 4+ внутри обычной ограды — её содержимое.
    "```\n    ```\ncode\n```\n<script>alert(12)</script>",
    # Переводы строк Windows и одиночный «\r» — тоже границы строк.
    "```\r\ncode\r\n```\r\n<script>alert(13)</script>\r\n",
    "# Заголовок `x\rтекст <script>alert(14)</script>` y",
])
def test_tidy_code_markers_inside_live_html_are_not_code(text):
    out = convert_to_md.tidy(text, keep_images=False)

    assert "onclick" not in out
    assert "<script" not in out
    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt(
        "commonmark", {"html": True}
    ).enable("table").render(out)
    assert "<script" not in html and "onclick" not in html


def test_tidy_keeps_code_fences_in_nested_lists():
    # Так MarkItDown пишет код во вложенном списке: ограда с отступом 4
    # после пустой строки. Это код, санитизация его не трогает.
    text = (
        "* item\n  + sub\n\n    ```\n"
        '    <script>x</script> onclick="1" data:x\n    ```\n\n'
        "1. step\n\n   ```\n   <iframe src=javascript:y>\n   ```\n"
    )

    assert convert_to_md.tidy(text, keep_images=False) == text


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


def test_xml_data_fence_keeps_whitespace_of_values(tmp_path):
    # В значениях XML пробелы и пустые строки — данные: MarkItDown
    # срезал «one  » и сжимал четыре перевода строки в два, tidy() —
    # тоже. В ограду идёт исходник, декодированный как парсером XML:
    # BOM, затем encoding из объявления, иначе UTF-8.
    cdata = "<root><v><![CDATA[one  \n\n\n\ntwo]]></v>\n<w>x   </w></root>"
    (tmp_path / "cdata.xml").write_text(cdata, encoding="utf-8")
    cp1251 = ('<?xml version="1.0" encoding="windows-1251"?>\n'
              "<r><![CDATA[Привет  \n\n\nмир]]></r>")
    (tmp_path / "cp1251.xml").write_bytes(cp1251.encode("cp1251"))
    (tmp_path / "utf16.xml").write_bytes(cdata.encode("utf-16"))
    out = tmp_path / "out"
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "sandbox": False,
        "scan": {".xml"}, "tool": "tomd", "planned": set(),
    }

    for name in ("cdata.xml", "cp1251.xml", "utf16.xml"):
        assert convert_to_md.convert_file(tmp_path / name, opts) == "ok"

    def body(stem):
        return (out / f"{stem}.md").read_text(encoding="utf-8")

    assert body("cdata") == f"```xml\n{cdata}\n```\n"
    assert body("cp1251") == f"```xml\n{cp1251}\n```\n"
    assert body("utf16") == f"```xml\n{cdata}\n```\n"


def _convert_xml(tmp_path, files: dict) -> dict:
    out = tmp_path / "out"
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out, "sandbox": False,
        "scan": {".xml"}, "tool": "tomd", "planned": set(),
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
        assert convert_to_md.convert_file(tmp_path / name, opts) == "ok"
    return {name: (out / name.replace(".xml", ".md")).read_text(
        encoding="utf-8") for name in files}


def test_xml_data_fence_reads_utf16_without_bom(tmp_path):
    # UTF-16 без BOM: порядок байтов — по началу «<?xml» (XML 1.0,
    # приложение F). Раньше такой файл проходил как UTF-8 с NUL, и
    # кириллица вычищалась вместе с ними: в ограде оставалось «<r></r>».
    def xml(encoding):
        return (f'<?xml version="1.0" encoding="{encoding}"?>\n'
                "<r><![CDATA[АБВ  \n\n\n\nГД]]></r>")

    bodies = _convert_xml(tmp_path, {
        "le.xml": xml("UTF-16LE").encode("utf-16-le"),
        "be.xml": xml("UTF-16BE").encode("utf-16-be"),
        "bare.xml": "<r>АБВ</r>".encode("utf-16-le"),
    })

    assert bodies["le.xml"] == f"```xml\n{xml('UTF-16LE')}\n```\n"
    assert bodies["be.xml"] == f"```xml\n{xml('UTF-16BE')}\n```\n"
    # Без объявления порядок байтов не определить — текст MarkItDown.
    assert "АБВ" in bodies["bare.xml"]


def test_xml_data_fence_survives_invisible_characters(tmp_path):
    # tidy() вырезает ZWSP; если длину ограды выбрать до этого, «```»,
    # ZWSP и «`» внутри данных становятся «````» — длиннее любой
    # видимой серии, — и закрывают ограду, а остаток выходит прозой.
    # Ограда выбирается по уже очищенному тексту — данные остаются
    # одним блоком кода.
    xml = ("<r><![CDATA[пример:\n```\u200b`\n"
           "Пояснение [x](data:field)\n```\n]]></r>")
    body = _convert_xml(tmp_path, {"zwsp.xml": xml.encode("utf-8")})[
        "zwsp.xml"]

    markdown_it = pytest.importorskip("markdown_it")
    html = markdown_it.MarkdownIt("commonmark").render(body)
    assert html.count("<pre>") == 1 and "<p>" not in html
    assert "Пояснение [x](data:field)" in html


def test_tidy_data_fence_does_not_disable_sanitizing():
    # Флаг data_fence бережёт только содержимое самой ограды: если
    # данные её всё же закрыли, текст после неё санитизируется.
    text = "```xml\n<r>\n```\nПояснение [x](javascript:alert(1)) data:x\n"

    out = convert_to_md.tidy(text, keep_images=False, data_fence=True)

    assert "javascript:" not in out and "data:x" not in out


def test_raw_xml_fenced_without_markitdown(tmp_path, monkeypatch):
    # CI 2.0.1 на Linux: MarkItDown выбирает конвертер XML по MIME-таблице
    # системы и отдавал .xml HTML-конвертеру (теги вырезались) или не
    # брал вовсе; на Windows — текстовому. Сырые данные огораживаются
    # без MarkItDown, на любой ОС.
    class Linuxish:
        def convert(self, path):
            if str(path).endswith(".xml") and "rss" not in str(path):
                return SimpleNamespace(title=None, text_content="v\n")
            return SimpleNamespace(title=None, text_content="# Лента\n")

    monkeypatch.setattr(convert_to_md, "_md", lambda: Linuxish())
    xml = '<?xml version="1.0"?>\n<root><k>v</k></root>'
    (tmp_path / "data.xml").write_text(xml, encoding="utf-8")
    rss = '<?xml version="1.0"?>\n<rss version="2.0"><channel/></rss>'
    (tmp_path / "rss.xml").write_text(rss, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out,
        "scan": {".xml"}, "tool": "tomd", "planned": set(),
    }
    assert convert_to_md.convert_file(tmp_path / "data.xml", opts) == "ok"
    assert convert_to_md.convert_file(tmp_path / "rss.xml", opts) == "ok"
    assert (out / "data.md").read_text("utf-8") == f"```xml\n{xml}\n```\n"
    assert "Лента" in (out / "rss.md").read_text("utf-8")


@pytest.mark.parametrize("name, xml", [
    ("prefixed", '<?xml version="1.0"?>\n'
                 '<a:feed xmlns:a="http://www.w3.org/2005/Atom">'
                 '<a:title>T</a:title></a:feed>'),
    ("comment", '<?xml version="1.0"?>\n<!-- Прежний формат: <item> -->\n'
                '<rss version="2.0"><channel/></rss>'),
])
def test_feeds_recognized_by_root_element(tmp_path, monkeypatch, name, xml):
    # Ревью Codex: лента Atom с префиксом и RSS с комментарием перед
    # корнем принимались за сырой XML и уходили в ограду.
    monkeypatch.setattr(convert_to_md, "_md", lambda: SimpleNamespace(
        convert=lambda path: SimpleNamespace(
            title=None, text_content="# Лента\n")))
    (tmp_path / f"{name}.xml").write_text(xml, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out,
        "scan": {".xml"}, "tool": "tomd", "planned": set(),
    }
    assert convert_to_md.convert_file(tmp_path / f"{name}.xml", opts) == "ok"
    assert (out / f"{name}.md").read_text("utf-8") == "# Лента\n"


def test_raw_xml_with_leading_line_still_fenced(tmp_path):
    # Строка диагностики перед выгрузкой: данные всё равно в ограде, с
    # пробелами в концах строк и пустыми строками внутри значений.
    xml = "Warning: export incomplete\n<rows><row>a  \n\n\n\nb</row></rows>"
    (tmp_path / "dump.xml").write_text(xml, encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    opts = {
        "force": True, "frontmatter": False, "keep_images": False,
        "unsafe_raw_markdown": False, "out_dir": out,
        "scan": {".xml"}, "tool": "tomd", "planned": set(),
    }
    assert convert_to_md.convert_file(tmp_path / "dump.xml", opts) == "ok"
    assert (out / "dump.md").read_text("utf-8") == f"```xml\n{xml}\n```\n"
