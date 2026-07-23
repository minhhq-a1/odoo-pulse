"""The JSON result boundary: run a client call and serialise the result (or a
friendly error) as JSON, so tool implementations never leak raw tracebacks.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from ..core.errors import OdooConfigError, OdooError


def safe(func: Callable[[], Any]) -> str:
    """Run a client call and serialise the result (or a friendly error) as JSON."""
    try:
        return json.dumps(func(), ensure_ascii=False, indent=2, default=str)
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
    except Exception as exc:  # shaping bugs must not leak raw tracebacks
        return json.dumps(
            {"error": f"internal error: {type(exc).__name__}: {exc}"},
            ensure_ascii=False,
            indent=2,
        )


def safe_text(func: Callable[[], str]) -> str:
    """Return raw success text while preserving the friendly JSON error boundary."""
    try:
        return func()
    except (OdooConfigError, OdooError) as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)
    except Exception as exc:  # shaping bugs must not leak raw tracebacks
        return json.dumps(
            {"error": f"internal error: {type(exc).__name__}: {exc}"},
            ensure_ascii=False,
            indent=2,
        )
