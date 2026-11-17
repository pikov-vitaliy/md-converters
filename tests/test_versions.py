"""Одна версия во всех местах: pyproject.toml, __version__ (её печатает
tomd --version и пишет в front matter) и package.json npm-пакета.
2.0.0 вышла с __version__ = "1.4.0" — этот тест её поймал бы."""
import json
import re
from pathlib import Path

import convert_to_md

ROOT = Path(__file__).resolve().parent.parent


def test_versions_match():
    py = re.search(r'^version\s*=\s*"([^"]+)"',
                   (ROOT / "pyproject.toml").read_text("utf-8"), re.M)
    npm = json.loads((ROOT / "package.json").read_text("utf-8"))
    assert py.group(1) == convert_to_md.__version__ == npm["version"]
