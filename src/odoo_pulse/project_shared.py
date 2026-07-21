# odoo_pulse/project_shared.py
"""Shared, non-tool helpers for the project-status tool family.

Everything here is read-only and client-agnostic (real OdooClient or the
test FakeClient). Budget primitives live in services/projects/budget.py
(single source of truth for planned/practical figures — spec rule #7);
analytic_money now lives in services/projects/profitability.py (single
source of truth for cost/revenue aggregates — same rule).
"""

from __future__ import annotations
