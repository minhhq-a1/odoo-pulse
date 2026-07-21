from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


def read_one(client: Any, model: str, record_id: int) -> dict:
    """Read exactly one record, raising if it doesn't exist.

    Not-found is an error here (a caller asking for one record by id
    wants that record, not silence) — a deliberate deviation from
    `read_records`, which returns [] for missing ids. On live Odoo a
    missing id usually raises MissingError server-side already (an
    OdooError via execute_kw); the empty-result check below is the
    defensive catch-all and the path the FakeClient exercises in tests.
    """
    rows = client.read(model, [record_id])
    if not rows:
        raise OdooError(f"{model} record {record_id} not found")
    return rows[0]
