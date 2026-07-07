"""Shared pytest fixtures: a fake Odoo client injected into the runtime so the
domain tools can be exercised without a real Odoo / network connection.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from odoo_pulse import runtime
from odoo_pulse.odoo_client import OdooError

_DEFAULT_FIELDS = {
    "name": {"type": "char", "string": "Name"},
    "sprint_id": {"type": "many2one", "string": "Sprint"},
    "mobile": {"type": "char", "string": "Mobile"},
    "project_id": {"type": "many2one", "string": "Project"},
}


class FakeClient:
    """Records the calls made by the tools and returns canned data.

    Tools call ``get_client().search_read(...)`` / ``read(...)`` etc. This fake
    captures the arguments (so tests can assert the model + domain that a tool
    built) and returns configurable responses keyed by model name.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        # model -> list[dict] returned by search_read
        self.search_responses: dict[str, list] = {}
        # model -> queue of row-lists; when non-empty, search_read pops one
        # per call (for tools that query the same model twice).
        self.search_responses_seq: dict[str, list] = {}
        # model -> queue of row-lists; when non-empty, aggregate_records pops
        # one per call (for tools that aggregate the same model twice).
        self.aggregate_responses_seq: dict[str, list] = {}
        # model -> list[dict] returned by read
        self.read_responses: dict[str, list] = {}
        self.raise_error: str | None = None
        self.config = SimpleNamespace(max_attachment_bytes=1048576, max_records=200)
        # (model, method) -> canned return value for execute_kw; falls back to True.
        self.execute_kw_responses: dict[tuple[str, str], object] = {}
        # model -> canned return value for search_count; falls back to 7.
        self.search_count_responses: dict[str, int] = {}
        # models whose search_read/search_count raise OdooError (to simulate
        # an app that is not installed).
        self.error_models: set[str] = set()
        # model -> fields_get schema dict; falls back to _DEFAULT_FIELDS.
        self.fields_responses: dict[str, dict] = {}
        # Major Odoo version reported by major_version()/aggregate_records;
        # tests override it to exercise the 18 vs 19 code paths.
        self.major: int | None = 18

    # -- helpers for tests --------------------------------------------------
    def last(self, method: str) -> dict:
        for call in reversed(self.calls):
            if call["method"] == method:
                return call
        raise AssertionError(f"No {method!r} call recorded; calls={self.calls}")

    # -- client surface used by the tools -----------------------------------
    def _maybe_raise(self) -> None:
        if self.raise_error:
            raise OdooError(self.raise_error)

    def version(self):
        self.calls.append({"method": "version"})
        self._maybe_raise()
        return {"server_version": "17.0", "protocol_version": 1}

    def list_models(self, name_filter=None):
        self.calls.append({"method": "list_models", "name_filter": name_filter})
        self._maybe_raise()
        return self.search_responses.get("ir.model", [])

    def fields_get(self, model, attributes=None):
        self.calls.append({"method": "fields_get", "model": model})
        self._maybe_raise()
        return self.fields_responses.get(model, dict(_DEFAULT_FIELDS))

    def search_count(self, model, domain=None):
        self.calls.append({"method": "search_count", "model": model, "domain": domain})
        self._maybe_raise()
        if model in self.error_models:
            raise OdooError(f"Object {model} doesn't exist")
        return self.search_count_responses.get(model, 7)

    def read(self, model, ids, fields=None):
        self.calls.append(
            {"method": "read", "model": model, "ids": ids, "fields": fields}
        )
        self._maybe_raise()
        return self.read_responses.get(model, [])

    def search_read(
        self, model, domain=None, fields=None, limit=None, offset=0, order=None
    ):
        self.calls.append(
            {
                "method": "search_read",
                "model": model,
                "domain": domain or [],
                "fields": fields,
                "limit": limit,
                "offset": offset,
                "order": order,
            }
        )
        self._maybe_raise()
        if model in self.error_models:
            raise OdooError(f"Object {model} doesn't exist")
        seq = self.search_responses_seq.get(model)
        if seq:
            return seq.pop(0)
        return self.search_responses.get(model, [])

    def create(self, model, values):
        self.calls.append({"method": "create", "model": model, "values": values})
        self._maybe_raise()
        return 101

    def write(self, model, ids, values):
        self.calls.append(
            {"method": "write", "model": model, "ids": ids, "values": values}
        )
        self._maybe_raise()
        return True

    def unlink(self, model, ids):
        self.calls.append({"method": "unlink", "model": model, "ids": ids})
        self._maybe_raise()
        return True

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.calls.append(
            {"method": method, "model": model, "args": args, "kwargs": kwargs}
        )
        self._maybe_raise()
        key = (model, method)
        if key in self.execute_kw_responses:
            return self.execute_kw_responses[key]
        return True

    def major_version(self):
        self.calls.append({"method": "major_version"})
        self._maybe_raise()
        return self.major

    def aggregate_records(
        self, model, group_by, measures, domain=None, limit=None, offset=0, order=None
    ):
        self.calls.append(
            {
                "method": "aggregate_records",
                "model": model,
                "group_by": group_by,
                "measures": measures,
                "domain": domain,
                "limit": limit,
                "offset": offset,
                "order": order,
            }
        )
        self._maybe_raise()
        method = (
            "formatted_read_group"
            if self.major is not None and self.major >= 19
            else "read_group"
        )
        seq = self.aggregate_responses_seq.get(model)
        if seq:
            rows = seq.pop(0)
        else:
            rows = self.search_responses.get(model, [])
        return {"method": method, "major_version": self.major, "rows": rows}


@pytest.fixture
def fake_client():
    fake = FakeClient()
    runtime._client = fake
    try:
        yield fake
    finally:
        runtime._client = None
