# Project finance consistency correction

Project finance outputs now share one accounting and budget-matching policy.

- Expense credits reduce cost; income credit notes reduce revenue when Odoo's
  `analytic_profitability` classifier is available.
- Older/custom instances without that field retain amount-sign classification
  and now expose `analytic_classification_fallback` instead of degrading
  silently.
- A budget line's explicit project is authoritative; only an unlinked line
  falls back through the project's analytic account.
- Mixed-sign planned/practical lines are added by magnitude, so `-100` and
  `+60` report `160`, not `40`.

No MCP tool name, argument, default, description, input schema, resource, or
tool-group membership changed. Existing dashboards may see corrected financial
values in the edge cases above; this is expected and is not source-data drift.
