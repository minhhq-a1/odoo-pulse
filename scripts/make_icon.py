#!/usr/bin/env python3
"""Render the odoo-pulse app icon to icon.png (512x512, rounded, dark).

A pulse/ECG waveform in the brand purple on a dark rounded square — small-size
legible for registry listings (Smithery/Glama) and reusable as a repo logo.
Run: python3 scripts/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

S = 512
BG = (13, 17, 23, 255)      # #0d1117
PANEL = (22, 27, 34, 255)   # #161b22
PURPLE = (167, 139, 250, 255)  # #a78bfa
GREEN = (63, 185, 80, 255)     # #3fb950


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return m


def main() -> int:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Dark rounded tile with a subtle inner panel border.
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=112, fill=BG)
    d.rounded_rectangle([26, 26, S - 27, S - 27], radius=90, outline=PANEL, width=4)

    # Left accent bar (echoes the brand mark).
    d.rounded_rectangle([70, 150, 90, 362], radius=10, fill=PURPLE)

    # ECG / pulse waveform across the middle.
    cy = 256
    pts = [
        (118, cy), (178, cy), (210, 150), (250, 384),
        (286, cy), (322, 210), (352, cy), (442, cy),
    ]
    d.line(pts, fill=PURPLE, width=20, joint="curve")
    # A small bright node at the peak for a bit of life.
    d.ellipse([242, 376, 258, 392], fill=GREEN)

    out = Path("icon.png")
    img.save(out)
    print(f"wrote {out} ({S}x{S})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
