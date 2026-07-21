# odoo_pulse/common/concurrency.py
"""Concurrency primitives shared by composed report/workflow tools."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable


def gather(
    thunks: dict[str, Callable[[], Any]], max_workers: int = 8
) -> dict[str, Any]:
    """Run independent zero-arg callables concurrently, one thread each.

    Returns {key: outcome} in the input's key order; outcome is the
    callable's return value or the exception instance it raised. The caller
    decides per key whether an exception is fatal (re-raise) or a degraded
    section (business_pulse). Safe over one OdooClient: it builds a fresh
    XML-RPC proxy per call and its caches are lock-guarded. A single thunk
    runs inline — no thread overhead for the trivial case.
    """

    def call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # captured; caller chooses to re-raise
            return exc

    if len(thunks) <= 1:
        return {key: call(fn) for key, fn in thunks.items()}
    with ThreadPoolExecutor(max_workers=min(len(thunks), max_workers)) as pool:
        futures = {key: pool.submit(call, fn) for key, fn in thunks.items()}
        return {key: futures[key].result() for key in thunks}


def gather_strict(
    thunks: dict[str, Callable[[], Any]], max_workers: int = 8
) -> dict[str, Any]:
    """:func:`gather` for callers where any failure is fatal.

    Re-raises the first exception in key order instead of returning it —
    the composed report tools want a single OdooError to surface through
    ``safe()`` exactly as it would have sequentially.
    """
    results = gather(thunks, max_workers)
    for outcome in results.values():
        if isinstance(outcome, Exception):
            raise outcome
    return results
