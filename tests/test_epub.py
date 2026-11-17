"""EPUB: главы из spine с относительными и %-кодированными href."""
import zipfile

import pytest

import convert_to_md


def _epub(path, href, member):
    """Минимальный EPUB: OPF в OEBPS/, одна глава с маркером."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles>'
            "</container>",
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package '
            'xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>Book</dc:title></metadata><manifest>"
            f'<item id="c1" href="{href}" '
            'media-type="application/xhtml+xml"/>'
            '</manifest><spine><itemref idref="c1"/></spine></package>',
        )
        z.writestr(
            f"OEBPS/{member}",
            "<html><body><p>CHAPTERMARKER</p></body></html>",
        )


@pytest.mark.parametrize("href, member", [
    ("./chapter.xhtml", "chapter.xhtml"),
    ("chap%20one.xhtml", "chap one.xhtml"),
])
def test_epub_spine_href_resolved_relative_to_opf(tmp_path, href, member):
    """b5: глава с ./ или %20 в href не теряется молча.

    MarkItDown 0.1.6 склеивал href с папкой OPF как строку и не
    находил главу в ZIP (оставались только метаданные). Разрешение
    URI относительно OPF пришло с MarkItDown 0.1.9 (нижняя граница
    в pyproject) — тест держит её от отката.
    """
    book = tmp_path / "book.epub"
    _epub(book, href, member)
    result, _ = convert_to_md._convert_file_data(book)
    assert "CHAPTERMARKER" in result.text_content
