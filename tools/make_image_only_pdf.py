"""Создаёт минимальный image-only PDF (одна страница, без текста).
Используется для ручного теста детектора image-only PDF.

Генерируется руками, без сторонних библиотек для записи PDF,
чтобы не раздувать тестовые зависимости.
"""
from pathlib import Path


def make_image_only_pdf(out: Path) -> None:
    """Минимальный валидный PDF с одной пустой страницей A4.
    Без шрифтов, без текста, без растровых объектов — гарантированно
    image-only с точки зрения извлечения текста."""
    body = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << >> >>\n"
        b"endobj\n"
        b"4 0 obj\n<< /Length 32 >>\nstream\n"
        b"0 0 m 595 0 l 595 842 l 0 842 l h\n"
        b"0 0 m S\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n"
        b"0000000010 00000 n \n0000000056 00000 n \n"
        b"0000000103 00000 n \n0000000200 00000 n \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n284\n%%EOF\n"
    )
    out.write_bytes(body)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: make_image_only_pdf.py <out.pdf>")
        sys.exit(2)
    make_image_only_pdf(Path(sys.argv[1]))
    print(f"Wrote {sys.argv[1]}")
