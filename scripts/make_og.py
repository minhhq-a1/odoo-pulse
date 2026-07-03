#!/usr/bin/env python3
"""Render the GitHub social-preview (OG) card to assets/og-card.png.

Self-contained: uses Pillow and macOS system fonts (falls back gracefully).
Run: python3 scripts/make_og.py
GitHub social preview wants a PNG/JPG ~1280x640 — upload it under
Settings → General → Social preview (web UI only).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 640
BG = "#0d1117"
FG = "#e6edf3"
MUTED = "#9198a1"
PURPLE = "#8b5cf6"
AMBER = "#f59e0b"
GREEN = "#3fb950"
CHIP_BG = "#161b22"
CHIP_BORDER = "#30363d"

FONTS = {
    "bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "regular": "/System/Library/Fonts/Supplemental/Arial.ttf",
    "mono": "/System/Library/Fonts/Menlo.ttc",
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONTS[kind], size)
    except Exception:
        return ImageFont.load_default()


def main() -> int:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Left accent bar.
    d.rectangle([0, 0, 12, H], fill=PURPLE)

    x = 80
    # Kicker.
    d.text((x, 84), "MODEL CONTEXT PROTOCOL SERVER", font=font("bold", 22),
           fill=PURPLE)
    # Title.
    d.text((x, 128), "odoo-pulse", font=font("bold", 104), fill=FG)
    # Tagline.
    d.text((x, 268), "An AI business analyst for your Odoo ERP",
           font=font("regular", 44), fill=FG)
    d.text((x, 330), "One call → numbers · highlights · risks · verdict",
           font=font("regular", 30), fill=MUTED)

    # Tool chips.
    chips = ["business_pulse", "pipeline_review", "receivables_health"]
    cx, cy = x, 430
    fchip = font("mono", 26)
    pad = 22
    for label in chips:
        tb = d.textbbox((0, 0), label, font=fchip)
        w = (tb[2] - tb[0]) + pad * 2
        if cx + w > W - 60:  # wrap before drawing so nothing clips the edge
            cx = x
            cy += 72
        d.rounded_rectangle([cx, cy, cx + w, cy + 56], radius=12,
                            fill=CHIP_BG, outline=CHIP_BORDER, width=2)
        d.text((cx + pad, cy + 12), label, font=fchip, fill=FG)
        cx += w + 16

    # Verdict badge (bottom).
    badge = "verdict: at-risk"
    fbadge = font("bold", 26)
    tb = d.textbbox((0, 0), badge, font=fbadge)
    bw = tb[2] - tb[0] + 44
    by = 540
    d.rounded_rectangle([x, by, x + bw, by + 54], radius=27,
                        fill="#3d2f00", outline=AMBER, width=2)
    d.text((x + 22, by + 12), badge, font=fbadge, fill=AMBER)

    # Footer handle.
    d.text((x, H - 46), "github.com/minhhq-a1/odoo-pulse",
           font=font("regular", 24), fill=MUTED)

    out = Path("assets/og-card.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"wrote {out} ({W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
