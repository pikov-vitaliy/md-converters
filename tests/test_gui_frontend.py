"""Логика фронтенда GUI (gui_static/index.html), исполненная в node.

Без fastapi: функции берутся из самой страницы и гоняются с
заглушками document/FormData, так что тест идёт и в CI без [gui].
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _js_function(source: str, name: str) -> str:
    """Текст функции верхнего уровня: от 'function name(' до '}' в
    начале строки (так оформлены все функции инлайн-скрипта)."""
    start = source.index(f"function {name}(")
    end = source.index("\n}\n", start) + 3
    return source[start:end]


@pytest.mark.skipif(NODE is None, reason="нужен node")
def test_flags_to_form_sends_unchecked_frontmatter():
    """c5: снятая галочка Front-matter уходит в FormData как false.

    flagsToForm пропускал false, сервер подставлял свой default
    frontmatter=True — YAML-шапка оставалась вопреки галочке.
    """
    html = (ROOT / "gui_static" / "index.html").read_text(encoding="utf-8")
    script = "\n".join([
        "const els = {force: {checked: false},",
        "  frontmatter: {checked: false}, keepImages: {checked: false},",
        "  pdfTables: {checked: true}, insecureSsl: {checked: false},",
        "  only: {value: ''}, outDir: {value: ''}};",
        "const document = {getElementById: (id) => els[id]};",
        "class FD { constructor() { this.items = []; }",
        "  append(k, v) { this.items.push([k, String(v)]); } }",
        _js_function(html, "getFlags"),
        _js_function(html, "flagsToForm"),
        "const fd = new FD(); flagsToForm(fd, false);",
        "console.log(JSON.stringify(fd.items));",
    ])
    done = subprocess.run(
        [NODE, "-"], input=script, capture_output=True,
        text=True, encoding="utf-8", timeout=60,
    )
    assert done.returncode == 0, done.stderr
    items = json.loads(done.stdout)
    assert ["frontmatter", "false"] in items
    assert ["force", "false"] in items
    # пустые поля (null) по-прежнему не шлются
    keys = [k for k, _ in items]
    assert "out_dir" not in keys
    assert "only" not in keys
