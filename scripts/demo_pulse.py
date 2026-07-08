#!/usr/bin/env python3
"""Render a `business_pulse` result as a Claude-style briefing and save it to SVG.

Used to generate the README hero image from *real* data (point it at the
playground or any Odoo). The SVG is self-contained and renders inline on GitHub,
so end users never need `rich` — only whoever regenerates the image does.

Usage:
    # against the playground (docker compose ... up):
    ODOO_URL=http://localhost:8069 ODOO_DB=playground \
    ODOO_USERNAME=admin ODOO_API_KEY=admin ODOO_READ_ONLY=true \
    python3 scripts/demo_pulse.py assets/business_pulse.svg
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console, Group
from rich.padding import Padding
from rich.text import Text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VERDICT_STYLE = {
    "attention": ("bold #f59e0b", "⚠ ATTENTION"),
    "all_clear": ("bold #22c55e", "✓ ALL CLEAR"),
}


def build_briefing() -> Group:
    from odoo_pulse.tools_reports import business_pulse

    report = json.loads(business_pulse())
    if "error" in report:
        raise SystemExit(f"business_pulse failed: {report['error']}")

    summary = report["summary"]
    as_of = report.get("as_of", "")
    verdict = summary.get("verdict", "")
    style, badge = VERDICT_STYLE.get(verdict, ("bold white", verdict.upper()))

    lines: list = []

    # Chat prompt.
    prompt = Text()
    prompt.append("▎ ", style="#6b7280")
    prompt.append("You\n", style="bold #6b7280")
    prompt.append("  Run business_pulse — how's the company doing today?",
                  style="#d1d5db")
    lines.append(prompt)
    lines.append(Text(""))

    # Claude's answer.
    answer = Text()
    answer.append("▎ ", style="#8b5cf6")
    answer.append("Claude\n", style="bold #8b5cf6")
    lines.append(answer)

    header = Text()
    header.append("  📊 Business Pulse", style="bold #e5e7eb")
    header.append(f"  ·  as of {as_of}\n", style="#9ca3af")
    lines.append(header)

    for h in report.get("highlights", []):
        t = Text("  • ", style="#22c55e")
        t.append(h, style="#e5e7eb")
        lines.append(t)

    risks = report.get("risks", [])
    if risks:
        lines.append(Text(""))
        lines.append(Text("  Needs attention", style="bold #f59e0b"))
        for r in risks:
            t = Text("  ⚠ ", style="#f59e0b")
            t.append(r["message"], style="#e5e7eb")
            lines.append(t)

    lines.append(Text(""))
    verdict_line = Text("  Verdict: ", style="#9ca3af")
    verdict_line.append(badge, style=style)
    lines.append(verdict_line)

    return Group(*lines)


def main() -> int:
    args = sys.argv[1:]
    if args == ["--print"]:
        # Animated-demo mode (vhs): render to the terminal, save nothing.
        Console(width=78).print(Padding(build_briefing(), (1, 1)))
        return 0
    out = Path(args[0]) if args else Path("assets/business_pulse.svg")
    console = Console(record=True, width=78)
    console.print(Padding(build_briefing(), (1, 1)))
    out.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(str(out), title="odoo-pulse · business_pulse")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
