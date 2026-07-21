# odoo_pulse/common/domains.py
"""Free-text search-domain primitive shared by every list/search tool."""

from __future__ import annotations


def name_domain(query: str | None, fields: list[str]) -> list:
    """Build an OR-of-ilike domain across `fields` for a free-text query.

    e.g. name_domain("acme", ["name", "email"]) ->
        ["|", ("name", "ilike", "acme"), ("email", "ilike", "acme")]
    """
    if not query:
        return []
    triplets = [(f, "ilike", query) for f in fields]
    if len(triplets) == 1:
        return [triplets[0]]
    return ["|"] * (len(triplets) - 1) + triplets
