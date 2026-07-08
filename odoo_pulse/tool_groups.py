"""Parse ODOO_TOOL_GROUPS into the list of tool modules the server loads.

Importing a tool module registers its @mcp.tool() functions as a side
effect, so choosing which modules server.py imports IS the tool filter.
Default surface is core + reports (27 tools); the breadth wrappers are
opt-in groups so they don't bloat the client's context window.
"""

from __future__ import annotations

import os

# group name -> module names inside the odoo_pulse package
GROUP_MODULES: dict[str, tuple[str, ...]] = {
    "core": ("tools_generic", "tools_write"),
    "reports": ("tools_workflows", "tools_reports", "tools_reports_ops"),
    "business": ("domain_tools",),
    "hr": ("tools_hr",),
    "projects": ("tools_projects",),
    "operations": ("tools_operations",),
    "engagement": ("tools_engagement",),
    "niche": ("tools_niche",),
}

DEFAULT_GROUPS = "core,reports"


def parse_groups(raw: str | None) -> list[str]:
    """Split a comma-separated group list, validated against GROUP_MODULES.

    "all" anywhere in the list enables every group. Unknown names raise
    ValueError so a config typo fails loudly at startup, not silently.
    Empty/None falls back to DEFAULT_GROUPS.
    """
    value = (raw or "").strip() or DEFAULT_GROUPS
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if "all" in names:
        return list(GROUP_MODULES)
    unknown = [n for n in names if n not in GROUP_MODULES]
    if unknown:
        raise ValueError(
            f"Unknown ODOO_TOOL_GROUPS entries: {', '.join(unknown)}. "
            f"Valid groups: {', '.join(GROUP_MODULES)}, all"
        )
    return names


def modules_to_load(raw: str | None = None) -> list[str]:
    """Ordered, de-duplicated module list for the enabled groups."""
    if raw is None:
        raw = os.environ.get("ODOO_TOOL_GROUPS")
    modules: list[str] = []
    for group in parse_groups(raw):
        for mod in GROUP_MODULES[group]:
            if mod not in modules:
                modules.append(mod)
    return modules
