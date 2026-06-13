"""PDF-специфичная диагностика: image-only / scan-only PDF.

Реальные PDF в репозитории не хранятся (бинарные, раздувают размер).
Тесты используют unittest.mock, чтобы не зависеть от MarkItDown и
от pypdfium2 при проверке логики диагностики.
"""
from types import SimpleNamespace

import convert_to_md


def test_text_layer_diagnose_present_for_text_rich_pdf():
    # 5 страниц, ~200 печатных символов на страницу = 1000 символов.
    text = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "Sed do eiusmod tempor incididunt ut labore et dolore magna. "
            * 5)
    # 5 страниц по 200 символов = 1000 символов, явно > 5*20=100.
    assert convert_to_md._pdf_text_layer_diagnose(text, 5) == "present"


def test_text_layer_diagnose_absent_for_image_only_pdf():
    # 5 страниц, но в результате MarkItDown — только пробелы и NUL.
    text = "   \x00 \x00 \x00   \x00\n\n  "
    assert convert_to_md._pdf_text_layer_diagnose(text, 5) == "absent"


def test_text_layer_diagnose_absent_for_completely_empty_pdf():
    assert convert_to_md._pdf_text_layer_diagnose("", 3) == "absent"


def test_text_layer_diagnose_returns_none_when_page_count_unknown():
    # Не PDF или не смогли открыть — диагностика не выполняется.
    assert convert_to_md._pdf_text_layer_diagnose("any text", None) is None


def test_text_layer_diagnose_returns_none_for_empty_pdf():
    # PDF без страниц — тоже None.
    assert convert_to_md._pdf_text_layer_diagnose("", 0) is None


def test_front_matter_includes_pdf_text_layer_when_provided():
    text = convert_to_md.front_matter(
        "report.pdf",
        title=None,
        tool="tomd",
        source_path="a/report.pdf",
        source_id="path:abcd",
        pdf_text_layer="absent",
    )
    assert 'pdf_text_layer: "absent"' not in text
    # без кавычек — это валидный YAML
    assert "pdf_text_layer: absent" in text


def test_front_matter_omits_pdf_text_layer_when_none():
    text = convert_to_md.front_matter(
        "report.html",
        title=None,
        tool="tomd",
        source_path="a/report.html",
        source_id="path:abcd",
        pdf_text_layer=None,
    )
    assert "pdf_text_layer" not in text


def test_front_matter_omits_pdf_text_layer_by_default():
    # pdf_text_layer — новый kwarg, должен быть необязательным.
    text = convert_to_md.front_matter(
        "report.html",
        title=None,
        tool="tomd",
        source_path="a/report.html",
        source_id="path:abcd",
    )
    assert "pdf_text_layer" not in text


def test_convert_file_emits_warning_for_image_only_pdf(tmp_path, monkeypatch):
    """PDF без текстового слоя: файл создаётся, но идёт [warning] в stderr,
    и в front-matter стоит pdf_text_layer: absent."""
    src = tmp_path / "scan.pdf"
    src.write_bytes(b"%PDF-1.4 fake")  # нам не важен реальный PDF — мок ниже
    out = tmp_path / "out"
    out.mkdir()
    target = out / "scan.md"

    # Мок: MarkItDown возвращает пустой/мусорный результат
    # (как image-only PDF).
    fake_result = SimpleNamespace(
        text_content="   \x00 \x00   ",
        title=None,
    )
    monkeypatch.setattr(
        convert_to_md, "_convert_file_data", lambda p: (fake_result, None)
    )
    # Мок: pypdfium2 «видит» 3 страницы.
    monkeypatch.setattr(convert_to_md, "_pdf_page_count", lambda p: 3)

    opts = {
        "force": True,
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "out_dir": out,
        "scan": {".pdf"},
        "tool": "tomd",
        "planned": set(),
    }

    status = convert_to_md.convert_file(src, opts)

    assert status == "ok"  # не fail
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "pdf_text_layer: absent" in body
    assert "[warning]" not in body  # warning идёт в stderr, не в файл


def test_convert_file_no_warning_for_text_rich_pdf(tmp_path, monkeypatch):
    """PDF с текстом: файл создаётся без warning, pdf_text_layer: present."""
    src = tmp_path / "rich.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()
    target = out / "rich.md"

    # Мок: MarkItDown возвращает нормальный текст.
    text = ("Lorem ipsum dolor sit amet. " * 100)  # ~2800 символов
    fake_result = SimpleNamespace(text_content=text, title=None)
    monkeypatch.setattr(
        convert_to_md, "_convert_file_data", lambda p: (fake_result, None)
    )
    monkeypatch.setattr(convert_to_md, "_pdf_page_count", lambda p: 3)

    opts = {
        "force": True,
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "out_dir": out,
        "scan": {".pdf"},
        "tool": "tomd",
        "planned": set(),
    }

    status = convert_to_md.convert_file(src, opts)

    assert status == "ok"
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "pdf_text_layer: present" in body


def test_convert_file_no_pdf_field_for_html(tmp_path, monkeypatch):
    """Не-PDF формат: pdf_text_layer НЕ появляется в front-matter."""
    src = tmp_path / "page.html"
    src.write_text("<h1>Hi</h1>", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    target = out / "page.md"

    fake_result = SimpleNamespace(
        text_content="# Hi\n\nПривет мир.\n", title=None
    )
    monkeypatch.setattr(
        convert_to_md, "_convert_file_data", lambda p: (fake_result, None)
    )
    # Мок: _pdf_page_count НЕ должен вызываться для .html, но проверим
    # что и при случайном вызове всё ок (страниц нет — диагностика
    # не делается).
    monkeypatch.setattr(convert_to_md, "_pdf_page_count", lambda p: None)

    opts = {
        "force": True,
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "out_dir": out,
        "scan": {".html"},
        "tool": "tomd",
        "planned": set(),
    }

    status = convert_to_md.convert_file(src, opts)

    assert status == "ok"
    body = target.read_text(encoding="utf-8")
    assert "pdf_text_layer" not in body


def test_pdf_page_count_handles_missing_pypdfium2(tmp_path, monkeypatch):
    """Если pypdfium2 недоступен, _pdf_page_count возвращает None."""
    src = tmp_path / "x.pdf"
    src.write_bytes(b"x")
    # Принудительно «отключаем» pypdfium2.
    monkeypatch.setattr(convert_to_md, "pypdfium2", None)
    assert convert_to_md._pdf_page_count(src) is None
