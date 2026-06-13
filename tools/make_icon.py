"""Сборка .ico из PNG-источника с несколькими разрешениями."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


def main(src: Path, dst: Path) -> int:
    if not src.is_file():
        print(f"Source PNG not found: {src}")
        return 1
    base = Image.open(src)
    if base.mode != "RGBA":
        base = base.convert("RGBA")
    sizes = [
        (16, 16), (24, 24), (32, 32), (48, 48),
        (64, 64), (128, 128), (256, 256),
    ]
    images = []
    for size in sizes:
        # LANCZOS — лучшее качество даунскейла.
        images.append(base.resize(size, Image.LANCZOS))
    images[-1].save(
        dst,
        format="ICO",
        sizes=[img.size for img in images],
        append_images=images[:-1],
    )
    sizes_str = ", ".join(f"{s[0]}x{s[1]}" for s in sizes)
    print(f"Wrote {dst} with sizes: {sizes_str}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: make_icon.py <source.png> <dest.ico>")
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
