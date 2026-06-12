import sys
from pathlib import Path
from types import SimpleNamespace

import convert_to_md


def test_parse_rejects_option_as_output_value():
    parsed = convert_to_md._parse(["file.html", "-o", "--force"])

    assert parsed["errors"]
    assert parsed["out_dir"] is None


def test_parse_rejects_option_as_only_value():
    parsed = convert_to_md._parse(["file.html", "--only", "--force"])

    assert parsed["errors"]
    assert parsed["only"] is None


def test_parse_rejects_path_like_only_value():
    parsed = convert_to_md._parse(["file.html", "--only", "../secret"])

    assert parsed["errors"]
    assert parsed["only"] is None


def test_parse_accepts_plain_and_dotted_extensions():
    parsed = convert_to_md._parse(["file.html", "--only", "pdf,.docx"])

    assert parsed["errors"] == []
    assert parsed["only"] == {".pdf", ".docx"}


def test_front_matter_contains_stable_source_fields():
    text = convert_to_md.front_matter(
        "report.html",
        title=None,
        tool="tomd",
        source_path="a/report.html",
        source_id="path:1234",
    )

    assert 'source: "report.html"' in text
    assert 'source_name: "report.html"' in text
    assert 'source_path: "a/report.html"' in text
    assert 'source_id: "path:1234"' in text


def test_output_dir_rerun_updates_matching_source_id(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    src_a = tmp_path / "a" / "report.html"
    src_b = tmp_path / "b" / "report.html"
    out_dir.mkdir()
    src_a.parent.mkdir()
    src_b.parent.mkdir()
    src_a.write_text("<h1>A</h1>", encoding="utf-8")
    src_b.write_text("<h1>B</h1>", encoding="utf-8")

    def fake_convert(path: Path):
        return SimpleNamespace(
            text_content=f"# {path.parent.name}\n",
            title=None,
        ), None

    monkeypatch.setattr(convert_to_md, "_convert_file_data", fake_convert)
    opts = {
        "force": True,
        "frontmatter": True,
        "keep_images": False,
        "out_dir": out_dir,
        "scan": {".html"},
        "tool": "tomd",
        "planned": set(),
    }

    assert convert_to_md.convert_file(src_a, opts) == "ok"
    assert convert_to_md.convert_file(src_b, opts) == "ok"

    def fake_convert_updated(path: Path):
        return SimpleNamespace(
            text_content=f"# {path.parent.name}-updated\n",
            title=None,
        ), None

    monkeypatch.setattr(
        convert_to_md,
        "_convert_file_data",
        fake_convert_updated,
    )
    rerun_opts = {**opts, "planned": set()}

    assert convert_to_md.convert_file(src_b, rerun_opts) == "ok"

    report_a = (out_dir / "report.md").read_text(encoding="utf-8")
    report_b = (out_dir / "report (2).md").read_text(encoding="utf-8")

    assert "# a\n" in report_a
    assert "# a-updated" not in report_a
    assert "# b-updated\n" in report_b


def test_file_target_planner_uses_source_id_for_output_dir_preflight(tmp_path):
    out_dir = tmp_path / "out"
    src_a = tmp_path / "a" / "report.html"
    src_b = tmp_path / "b" / "report.html"
    out_dir.mkdir()
    src_a.parent.mkdir()
    src_b.parent.mkdir()
    src_a.write_text("<h1>A</h1>", encoding="utf-8")
    src_b.write_text("<h1>B</h1>", encoding="utf-8")
    source_id_a = convert_to_md._source_id_for_path(src_a)
    source_id_b = convert_to_md._source_id_for_path(src_b)
    (out_dir / "report.md").write_text(
        convert_to_md.front_matter(
            src_a.name,
            title=None,
            tool="tomd",
            source_path=str(src_a),
            source_id=source_id_a,
        ),
        encoding="utf-8",
    )
    (out_dir / "report (2).md").write_text(
        convert_to_md.front_matter(
            src_b.name,
            title=None,
            tool="tomd",
            source_path=str(src_b),
            source_id=source_id_b,
        ),
        encoding="utf-8",
    )
    opts = {"out_dir": out_dir}

    target, source_id = convert_to_md._plan_file_target(src_b, opts, set())

    assert target == out_dir / "report (2).md"
    assert source_id == source_id_b


def test_source_id_uses_128_bits_and_matches_legacy_prefix(tmp_path):
    src = tmp_path / "doc.html"
    src.write_text("<h1>x</h1>", encoding="utf-8")

    source_id = convert_to_md._source_id_for_path(src)
    kind, digest = source_id.split(":", 1)

    assert kind == "path"
    assert len(digest) == 32
    assert convert_to_md._source_id_matches(
        f"path:{digest[:16]}",
        source_id,
    )


def test_cli_pdf_and_html_pass_default_filters(monkeypatch):
    calls = []

    def fake_main(argv, default_only):
        calls.append((argv, default_only))
        return 0

    monkeypatch.setattr(convert_to_md, "_main", fake_main)
    monkeypatch.setattr(sys, "argv", ["pdf2md", "report"])

    assert convert_to_md.cli_pdf() == 0

    monkeypatch.setattr(sys, "argv", ["html2md", "page"])

    assert convert_to_md.cli_html() == 0
    assert calls == [
        (["report"], ["pdf"]),
        (["page"], ["html", "htm"]),
    ]


def test_parse_version_prints_current_version(capsys):
    try:
        convert_to_md._parse(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    output = capsys.readouterr().out
    assert f"md-converters {convert_to_md.__version__}" in output
