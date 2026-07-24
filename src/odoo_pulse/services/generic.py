from __future__ import annotations

from typing import Any

from ..core.errors import OdooError


ALLOWED_AGGREGATORS = frozenset(
    {"sum", "avg", "min", "max", "count", "count_distinct"}
)
ATTACHMENT_META_FIELDS = [
    "name", "mimetype", "file_size", "type", "url", "res_model",
    "res_id", "checksum", "create_date",
]


def get_odoo_version(client: Any) -> dict:
    info = dict(client.version())
    major = client.major_version()
    if major is not None and major < 18:
        info["warning"] = (
            "odoo-pulse targets Odoo 18+; report tools are not "
            "guaranteed on this version."
        )
    return info


def list_models(client: Any, name_filter: str | None = None) -> list[dict]:
    return client.list_models(name_filter)


def get_model_fields(client: Any, model: str,
                     fields: list[str] | None = None) -> dict:
    result = client.fields_get(model)
    if not fields:
        return result
    selected = set(fields)
    return {name: meta for name, meta in result.items() if name in selected}


def search_records(client: Any, model: str, *, domain: list | None = None,
                   fields: list[str] | None = None, limit: int | None = None,
                   offset: int = 0, order: str | None = None) -> list[dict]:
    return client.search_read(
        model, domain=domain, fields=fields, limit=limit,
        offset=offset, order=order,
    )


def count_records(client: Any, model: str,
                  domain: list | None = None) -> dict:
    return {"count": client.search_count(model, domain)}


def read_records(client: Any, model: str, ids: list[int],
                 fields: list[str] | None = None) -> list[dict]:
    return client.read(model, ids, fields)


def parse_measures(measures: list[str] | None) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for spec in measures or []:
        field, separator, aggregator = spec.partition(":")
        field = field.strip()
        aggregator = (aggregator.strip() or "sum") if separator else "sum"
        if not field:
            raise OdooError(f"Invalid measure spec: {spec!r}")
        if aggregator not in ALLOWED_AGGREGATORS:
            raise OdooError(
                f"Unsupported aggregator {aggregator!r} in {spec!r}; "
                f"allowed: {sorted(ALLOWED_AGGREGATORS)}"
            )
        parsed.append((field, aggregator))
    return parsed or [("id", "count")]


def aggregate_records(client: Any, model: str, group_by: list[str], *,
                      measures: list[str] | None = None,
                      domain: list | None = None, limit: int | None = None,
                      offset: int = 0, order: str | None = None) -> dict:
    if not group_by:
        raise OdooError("group_by must contain at least one field.")
    parsed = parse_measures(measures)
    result = client.aggregate_records(
        model, group_by, parsed, domain=domain, limit=limit,
        offset=offset, order=order,
    )
    rows = result["rows"]
    return {
        "method": result["method"],
        "major_version": result["major_version"],
        "model": model,
        "group_by": group_by,
        "measures": [f"{field}:{aggregator}" for field, aggregator in parsed],
        "row_count": len(rows),
        "rows": rows,
    }


def read_attachment(client: Any, attachment_id: int,
                    include_data: bool = True) -> dict:
    cap = client.config.max_attachment_bytes
    rows = client.read(
        "ir.attachment", [attachment_id], ATTACHMENT_META_FIELDS
    )
    if not rows:
        raise OdooError(f"Attachment {attachment_id} not found.")
    attachment = rows[0]
    warnings: list[str] = []
    data_base64 = None
    data_included = False
    if attachment.get("type") == "url":
        warnings.append("Attachment is a URL link; no binary data. See 'url'.")
    elif include_data:
        size = attachment.get("file_size") or 0
        if size <= cap:
            blob = client.read("ir.attachment", [attachment_id], ["datas"])
            data_base64 = blob[0].get("datas") if blob else None
            data_included = data_base64 is not None
        else:
            warnings.append(
                f"file_size {size} exceeds ODOO_MAX_ATTACHMENT_BYTES "
                f"({cap}); data omitted."
            )
    return {
        "attachment": attachment,
        "data_base64": data_base64,
        "data_included": data_included,
        "max_bytes": cap,
        "warnings": warnings,
    }
