from types import SimpleNamespace

import convert_to_md


def _base_opts(tmp_path):
    return {
        "force": True,
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "out_dir": tmp_path / "out",
        "scan": {".html"},
        "tool": "tomd",
        "planned": set(),
        "max_input_mb": 1 / (1024 * 1024),
        "max_input_bytes": 1,
        "conversion_timeout": 5,
        "sandbox": False,
    }


def test_parse_resource_limit_flags():
    parsed = convert_to_md._parse([
        "file.html",
        "--max-input-mb",
        "12",
        "--conversion-timeout",
        "7",
        "--no-sandbox",
    ])

    assert parsed["errors"] == []
    assert parsed["max_input_mb"] == 12.0
    assert parsed["conversion_timeout"] == 7.0
    assert parsed["sandbox"] is False


def test_parse_rejects_invalid_resource_limits():
    parsed = convert_to_md._parse([
        "file.html",
        "--max-input-mb",
        "0",
        "--conversion-timeout",
        "-1",
    ])

    assert parsed["errors"]


def test_convert_file_rejects_large_input_before_parser(tmp_path, monkeypatch):
    src = tmp_path / "large.html"
    src.write_text("too large", encoding="utf-8")
    opts = _base_opts(tmp_path)

    def fail_if_called(path):
        raise AssertionError("parser should not be called")

    monkeypatch.setattr(convert_to_md, "_convert_file_data", fail_if_called)

    assert convert_to_md.convert_file(src, opts) == "fail"
    assert not (opts["out_dir"] / "large.md").exists()


def test_subprocess_runner_uses_hidden_worker_and_timeout(
    tmp_path,
    monkeypatch,
):
    src = tmp_path / "doc.html"
    target = tmp_path / "doc.md"
    src.write_text("<h1>ok</h1>", encoding="utf-8")
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="done\n", stderr="")

    monkeypatch.setattr(convert_to_md.subprocess, "run", fake_run)
    opts = {
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "tool": "tomd",
        "conversion_timeout": 9,
    }

    status = convert_to_md._convert_file_subprocess(
        src,
        target,
        opts,
        ".html",
        "path:abc",
    )

    assert status == "ok"
    assert "--_worker-convert" in calls["command"]
    assert calls["kwargs"]["timeout"] == 9
    assert calls["kwargs"]["errors"] == "strict"


def test_subprocess_runner_fails_on_non_utf8_worker_output(
    tmp_path,
    monkeypatch,
):
    src = tmp_path / "doc.html"
    target = tmp_path / "doc.md"
    src.write_text("<h1>ok</h1>", encoding="utf-8")

    def fake_run(command, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start")

    monkeypatch.setattr(convert_to_md.subprocess, "run", fake_run)
    opts = {
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "tool": "tomd",
        "conversion_timeout": 9,
    }

    status = convert_to_md._convert_file_subprocess(
        src,
        target,
        opts,
        ".html",
        "path:abc",
    )

    assert status == "fail"
