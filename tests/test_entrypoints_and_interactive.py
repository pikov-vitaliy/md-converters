import builtins
import json

import convert_to_md


def test_worker_convert_parses_payload_and_returns_success(
    monkeypatch,
    tmp_path,
):
    calls = {}

    def fake_convert(path, target, opts, suffix, source_id):
        calls["path"] = path
        calls["target"] = target
        calls["opts"] = opts
        calls["suffix"] = suffix
        calls["source_id"] = source_id
        return "ok"

    monkeypatch.setattr(convert_to_md, "_convert_file_to_target", fake_convert)
    payload = json.dumps({
        "frontmatter": True,
        "keep_images": False,
        "unsafe_raw_markdown": False,
        "tool": "tomd",
    })

    code = convert_to_md._worker_convert([
        str(tmp_path / "in.html"),
        str(tmp_path / "out.md"),
        ".html",
        "path:abc",
        payload,
    ])

    assert code == 0
    assert calls["suffix"] == ".html"
    assert calls["source_id"] == "path:abc"
    assert calls["opts"]["tool"] == "tomd"


def test_interactive_prompts_for_existing_target_and_sets_force(
    monkeypatch,
    tmp_path,
):
    src = tmp_path / "doc.html"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    src.write_text("<h1>ok</h1>", encoding="utf-8")
    (out_dir / "doc.md").write_text(
        convert_to_md.front_matter(
            src.name,
            title=None,
            tool="tomd",
            source_path=str(src),
            source_id=convert_to_md._source_id_for_path(src),
        ),
        encoding="utf-8",
    )
    responses = iter([
        f"{src} -o {out_dir}",
        "y",
        "",
    ])
    runs = []

    def fake_run(items, opts):
        runs.append((items, opts.copy()))
        return []

    monkeypatch.setattr(builtins, "input", lambda prompt="": next(responses))
    monkeypatch.setattr(convert_to_md, "run", fake_run)

    convert_to_md.interactive(default_only=None)

    assert len(runs) == 1
    assert runs[0][0] == [src]
    assert runs[0][1]["force"] is True
