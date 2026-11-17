import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")


def _section(start: str, end: str) -> str:
    """Кусок install.ps1 между маркерами (без самого end)."""
    script = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    i = script.index(start)
    return script[i:script.index(end, i)]


def _run_pwsh(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Только переданный кусок, в pwsh -NoProfile: профиль не читается
    и не пишется, настоящий install.ps1 не запускается."""
    probe = tmp_path / "probe.ps1"
    probe.write_text(
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        + body,
        encoding="utf-8-sig",
    )
    return subprocess.run(
        [PWSH, "-NoProfile", "-NonInteractive", "-File", str(probe)],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


# Заглушка python: pip install отвечает кодом FAKE_PIP, всё прочее
# (импорт модулей) — FAKE_IMPORT. Вызовы копятся в $global:calls.
_FAKE_PYTHON = """
$global:calls = @()
$python = {
    $line = $args -join ' '
    $global:calls += $line
    if ($line -like '-m pip install*') {
        $global:LASTEXITCODE = [int]$env:FAKE_PIP
    } else {
        $global:LASTEXITCODE = [int]$env:FAKE_IMPORT
    }
}
$kit = 'C:\\kit'
"""


@pytest.mark.skipif(PWSH is None, reason="нужен pwsh")
@pytest.mark.parametrize("pip_code, ok", [(1, False), (0, True)])
def test_install_reports_pip_failure(tmp_path, monkeypatch, pip_code, ok):
    """c8: упавший pip не превращается в «Комплект установлен.».

    Импорт ранее стоявших модулей проходил и затирал $LASTEXITCODE
    ошибки pip — установщик рапортовал успех со старым пакетом.
    """
    block = _section("# --- 2)", "# --- 3)")
    monkeypatch.setenv("FAKE_PIP", str(pip_code))
    monkeypatch.setenv("FAKE_IMPORT", "0")
    done = _run_pwsh(tmp_path, _FAKE_PYTHON + block + "\nexit 0\n")
    if ok:
        assert done.returncode == 0, done.stdout + done.stderr
        assert "Комплект установлен." in done.stdout
    else:
        assert done.returncode == 1, done.stdout + done.stderr
        assert "Комплект установлен." not in done.stdout
        assert "Не удалось установить" in done.stdout


def test_sendto_shortcut_gets_explicit_icon_location():
    script = (ROOT / "install.ps1").read_text(encoding="utf-8-sig")
    start = script.index("# --- 4-1) Send to")
    end = script.index("# --- 4-2)")
    sendto_block = script[start:end]

    assert "$lnk.IconLocation     = $iconValue" in sendto_block
    assert sendto_block.index("$lnk.IconLocation") < sendto_block.index(
        "$lnk.Save()",
    )
    assert "$check.IconLocation -ine $iconValue" in sendto_block
