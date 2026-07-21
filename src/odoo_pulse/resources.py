"""MCP resource: odoo://{model}/{id} — one live Odoo record as JSON.

odoo-pulse's first (and so far only) MCP Resource; everything else is a
tool. Registered as a resource *template*: clients see it via
resources/templates/list, not the plain resources/list. The SDK coerces
`id` from the URI string to int via pydantic.validate_call; `id` shadows
the builtin deliberately — the SDK requires URI param names to match
function param names exactly.

Not-found is an error here (one URI addresses exactly one record), a
deliberate deviation from `read_records`, which returns [] for missing
ids. On live Odoo a missing id usually raises MissingError server-side
(already an OdooError via execute_kw); the empty-result check below is
the defensive catch-all and the path the FakeClient exercises.
"""

from __future__ import annotations

from .odoo_client import OdooError
from .runtime import get_client, mcp, safe


def _read_one(model: str, rec_id: int) -> dict:
    rows = get_client().read(model, [rec_id])
    if not rows:
        raise OdooError(f"{model} record {rec_id} not found")
    return rows[0]


@mcp.resource("odoo://{model}/{id}", mime_type="application/json")
def odoo_record(model: str, id: int) -> str:
    """One Odoo record with all stored fields, e.g. odoo://res.partner/5."""
    return safe(lambda: _read_one(model, id))
