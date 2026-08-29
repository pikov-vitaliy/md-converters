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


def test_repair_broken_cyrillic_pdf_font_mapping():
    broken = (
        "НастояIая Методика выявления уя7вимосте9 и "
        "недекларированных во7можносте9 в программном "
        "о1еспеGении. "
    ) * 4

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(broken)

    assert "Настоящая Методика выявления уязвимостей" in repaired
    assert "недекларированных возможностей" in repaired
    assert "программном обеспечении" in repaired


def test_repair_broken_cyrillic_ignores_normal_mixed_text():
    normal = (
        "ГОСТ Р 56939-2024. Версия Python 3.14. "
        "Контроль SHA256 и раздел 4.2."
    )

    assert (
        convert_to_md._repair_broken_cyrillic_pdf_text(normal) == normal
    )


# Сноски в ведомственных PDF набраны вторым шрифтом с другой (сдвинутой
# на четыре буквы) сломанной картой. Основная карта их не расшифровывает,
# а её слепое применение превращает текст в другую бессмыслицу.
_ALT_FONT_BODY = (
    "НастояIая Методика выявления уя7вимосте9 и "
    "недекларированных во7можносте9 в программном "
    "о1еспеGении.\n"
) * 4


def test_repair_alternate_font_footnote_lines():
    text = _ALT_FONT_BODY + (
        "11 \x1fD< BJ9A>9 <ECB?P;B64A<я CD<@9A<@OI BCJ<= "
        "<ECOF4F9?PAB= ?45BD4FBD<< E?98G9F GK<FO64FP\n"
        "CB CB6OL9A<N 59;BC4EABEF< CDB7D4@@AOI >B@CBA9AFB6.\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "При оценке использования применимых опций" in repaired
    assert "испытательной лаборатории следует учитывать" in repaired
    assert "по повышению безопасности программных" in repaired
    # Основная карта не должна оставлять на этих строках свой мусор.
    assert "лтждсмя" not in repaired
    assert "утпткйсмя" not in repaired


def test_repair_alternate_font_keeps_digits_and_urls():
    text = _ALT_FONT_BODY + (
        "20!C9J<H<>4J<я HBD@4F4 "
        "https://github.com/package-url/purl-spec\n"
        "!\" 71206-2024 « 4;D45BF>4 59;BC4EAB7B CDB7D4@@AB7B "
        "B59EC9K9A<я.\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "спецификация формата".casefold()[1:] in repaired.casefold()
    assert "https://github.com/package-url/purl-spec" in repaired
    assert "71206-2024" in repaired
    assert "разработка безопасного программного".casefold()[1:] in (
        repaired.casefold()
    )


def test_repair_alternate_font_leaves_normal_lines_alone():
    text = _ALT_FONT_BODY + (
        "(ИСО 8601:2004).\n"
        "Например, «2022-04-25T09:30:00Z»\n"
        "GOST:security_function, то поле value должно\n"
        "Модуль Nginx: САО.1, ДАО.1, ДАО.2 (поверхность атаки);\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "(ИСО 8601:2004)." in repaired
    assert "«2022-04-25T09:30:00Z»" in repaired
    assert "GOST:security_function, то поле value должно" in repaired
    assert "Модуль Nginx: САО.1, ДАО.1, ДАО.2" in repaired


def test_repair_keeps_trailing_enumeration_punctuation():
    # Двоеточие и точка с запятой в конце слова — настоящая пунктуация,
    # а не буквы `к`/`л`: перечислений в таких документах сотни.
    text = _ALT_FONT_BODY + (
        "ПримеGание: анали7ируNтся:\n"
        "требования доверия; о1раIение к кода;\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "Примечание: анализируются:" in repaired
    assert "доверия;" in repaired
    assert "кода;" in repaired
    assert "довериял" not in repaired
    assert "анализируютсяк" not in repaired


def test_repair_decodes_trailing_letter_lookalikes():
    # `<`, `=`, `>`, `@` в конце слова — буквы (`м`,`н`,`о`,`р`),
    # пунктуацией в русском тексте они слово не завершают.
    text = _ALT_FONT_BODY + (
        "исс;54>2а=иO< и исс;54>2аB5;Lск>3> подхода\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "исследованиям" in repaired
    assert "исследовательского" in repaired


def test_repair_restores_letter_when_word_known_in_document():
    # Если буква достраивает слово, встречающееся в документе целым,
    # концевой `;` — всё-таки буква, а не пунктуация.
    text = _ALT_FONT_BODY + (
        "Настоящий материал содержит требования\n"
        "иEC>;L7у5Bся <аB5@иа; в полном объеме\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "материал в полном объеме" in repaired
    assert "материа;" not in repaired


def test_repair_decodes_all_ascii_word_known_in_document():
    # Прогон без единой уцелевшей буквы переводится, только если
    # результат встречается в документе целым словом.
    text = _ALT_FONT_BODY + (
        "Модельный пример и его модельного анализа\n"
        "Краткое описание <>45;L=>3> ОО версии 1.2\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "Краткое описание модельного ОО" in repaired
    assert "версии 1.2" in repaired


def test_repair_uses_words_recovered_in_first_pass():
    # Слово встречается в документе только сломанным: один раз с
    # уцелевшей буквой (чинится сразу), другой — сплошным ASCII.
    # Второй проход достраивает словарь результатами первого и
    # добирает прогон, на который в сыром тексте улик не было.
    text = _ALT_FONT_BODY + (
        "Перечень м>4C;59 приведен в таблице\n"
        "Количество <>4C;59 в составе ОО\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "Перечень модулей приведен" in repaired
    assert "Количество модулей в составе" in repaired


def test_repair_keeps_technical_designations_intact():
    # Словарь второго прохода вдвое больше словаря первого, поэтому
    # важно, что обозначения (модели, версии, даты, аббревиатуры) под
    # него не подпадают: их «перевод» дал бы не заметный глазом мусор
    # («С2000» -> «Свааа»). Граница шлюза — здесь.
    text = _ALT_FONT_BODY + (
        "Контроллер С2000 и панель С2000М в составе ОО\n"
        "Стандарт 8601:2004 и время 09:30:00 в отGете\n"
        "Требования ОО; АРМ: НДВ; САО: перечислены выше\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "Контроллер С2000 и панель С2000М в составе ОО" in repaired
    assert "Стандарт 8601:2004 и время 09:30:00 в отчете" in repaired
    assert "Требования ОО; АРМ: НДВ; САО: перечислены выше" in repaired


def test_repair_restores_capitals_hidden_in_alt_font_punctuation():
    # Во втором шрифте заглавные Р..Я лежат в печатных 0x20..0x2F:
    # «Р» — это пробел, «С» — «!», «Т» — «"». Слепой перевод уничтожил
    # бы настоящие пробелы, поэтому заглавная возвращается только по
    # улике из самого документа.
    text = _ALT_FONT_BODY + (
        "Разработка безопасного ПО. Разработка идет по плану.\n"
        "Требования ФСТЭК России учтены. Методики России тоже.\n"
        'D9>B@9A84J<< Ф!"ЭК BEE<< « 4;D45BF>4 59;BC4EAB7B\n'
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    # Пробел перед «оссии» — разделитель слов И буква «Р» сразу.
    assert "рекомендации ФСТЭК России" in repaired
    # А после кавычки тот же пробел — только буква, без разделителя.
    assert "«Разработка безопасного" in repaired


def test_repair_keeps_real_punctuation_in_alt_font():
    # Граница правила: «/» и «+» здесь настоящие, а не буквы «Я»/«Ы»,
    # и подтверждения в документе у них нет.
    text = _ALT_FONT_BODY + (
        "Компилятор языков С/С++ описан в отдельном разделе.\n"
        '>B@C<?яFBD я;O>B6 !/!++», 4 F4>:9 @9FB8<K9E><9\n'
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "компилятор языков" in repaired
    assert "также методические" in repaired
    assert "СЯСЫЫ" not in repaired
    assert "Ы" not in repaired.split("\n")[-2]


def test_repair_leaves_unknown_all_ascii_runs_alone():
    # Даты и стандарты словарём не подтверждаются — остаются как есть.
    text = _ALT_FONT_BODY + (
        "Формат даты по стандарту 8601:2004 указан в приложении\n"
    )

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(text)

    assert "по стандарту 8601:2004 указан" in repaired


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


def test_convert_file_uses_pdfium_text_for_russian_text_layer(
    tmp_path, monkeypatch
):
    """Русский текстовый слой диагностируется по PDF, а не по markdown.

    На некоторых PDF MarkItDown/pdfminer может вернуть короткий мусор для
    кириллицы. Если pypdfium2 видит нормальный текстовый слой, файл нельзя
    помечать как scan/image-only.
    """
    src = tmp_path / "russian.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()
    target = out / "russian.md"

    fake_result = SimpleNamespace(text_content="??", title=None)
    monkeypatch.setattr(
        convert_to_md, "_convert_file_data", lambda p: (fake_result, None)
    )
    monkeypatch.setattr(convert_to_md, "_pdf_page_count", lambda p: 3)
    monkeypatch.setattr(
        convert_to_md,
        "_pdf_text_layer_probe",
        lambda p: ("Привет мир. " * 80, 3),
        raising=False,
    )

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
    assert "Привет мир." in body
    assert "\n??\n" not in body


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


def test_repair_ignores_ocr_scan_with_sparse_noise():
    """OCR-скан с редким шумом не принимается за сломанный шрифт.

    На скане ГОСТ Р 34.11-2012 гейт проходил впритык (1.01% при
    прежнем пороге 1%), и ремонт молча портил криптографические
    константы: «345» внутри хэша декодировалось в частое слово «где»,
    которое словарь документа ложно подтверждал. У настоящего
    сломанного шрифта плотность дефектных символов ≥7% даже на
    коротких фрагментах (буквы а-п уходят в ASCII массово), у
    OCR-шума скана — около 1%. Синтетика ниже собрана в зазор
    1-3%: старый гейт на ней срабатывал и портил текст.
    """
    prose = (
        "Настоящий стандарт устанавливает функцию хэширования, где "
        "значение вычисляется по алгоритму подстановки и перестановки "
        "для обеспечения целостности сообщений и защиты информации. "
    ) * 14
    noise = " ".join(
        f"шум{n}величина512и256равна задаётся efed29dc345e53d"
        for n in range(10)
    )
    text = prose + noise

    assert convert_to_md._repair_broken_cyrillic_pdf_text(text) == text


def test_repair_keeps_pure_digit_runs_in_broken_document():
    """Чисто цифровой прогон не переводится и в сломанном документе.

    «345» декодируется в «где», «157» — в «без»: словарь подтверждает
    частые слова, и настоящие числа (значения подстановок, hex)
    молча превращались бы в прозу. Видимо сломанное «345» честнее
    невидимой порчи числа.
    """
    broken = (
        "НастояIая Методика выявления уя7вимосте9, где числа "
        "о1еспеGения це;остности и values 345 и 157, 158 остаются. "
    ) * 4

    repaired = convert_to_md._repair_broken_cyrillic_pdf_text(broken)

    assert "Настоящая Методика выявления уязвимостей" in repaired
    assert "345" in repaired
    assert "157, 158" in repaired
    assert "где" not in repaired.replace("где числа", "")


def test_markitdown_fallback_strips_page_furniture(tmp_path, monkeypatch):
    """Фолбэк MarkItDown тоже чистит колонтитулы и номера страниц.

    PDF без геометрических таблиц уходит мимо _pdf_tables_result, и
    _clean_pdf_text на него не действовал: в Р 71207-2024 в .md
    оставались 19 колонтитулов «ГОСТ Р 71207—2024» и голые номера
    страниц — тогда как соседний Р 71206-2024 (pdfplumber-путь) те же
    колонтитулы срезал. Чистка колонтитулов обязана работать и на
    фолбэке; фенсинг и экранирование — нет (настроены на
    pdfplumber-текст).
    """
    src = tmp_path / "plain.pdf"
    src.write_bytes(b"%PDF-1.4 fake")
    out = tmp_path / "out"
    out.mkdir()

    pages = "\n".join(
        f"ПНСТ 123—2024\n"
        f"Содержательный текст страницы {i} о требованиях "
        f"безопасности разработки программного обеспечения.\n{i}"
        for i in range(1, 13)
    )
    fake_result = SimpleNamespace(text_content=pages, title=None)
    monkeypatch.setattr(
        convert_to_md, "_pdf_tables_result", lambda p: None
    )
    monkeypatch.setattr(
        convert_to_md, "_convert_file_data", lambda p: (fake_result, None)
    )
    monkeypatch.setattr(
        convert_to_md, "_pdf_text_layer_probe", lambda p: (pages, 12)
    )

    opts = {
        "force": True,
        "frontmatter": False,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "out_dir": out,
        "scan": {".pdf"},
        "tool": "tomd",
        "planned": set(),
    }

    status = convert_to_md.convert_file(src, opts)

    assert status == "ok"
    body = (out / "plain.md").read_text(encoding="utf-8")
    assert "ПНСТ 123—2024" not in body
    assert "Содержательный текст страницы 3" in body
