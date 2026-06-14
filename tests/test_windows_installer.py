from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
