# Roadmap

Follow-up work deferred from the 2026-07 analyst-gap closure
(`docs/superpowers/plans/2026-07-03-analyst-gaps.md`). Nothing here is
scheduled — pick items up when a real need appears.

## Trend bucketing: move server-side

`sales_snapshot`'s `weekly_revenue` trend currently fetches up to 200 raw
`sale.order` rows and buckets them into weeks client-side
(`src/odoo_pulse/tools_reports_sales.py`, `sales_snapshot`). On an instance with more
than ~200 confirmed orders in the trend window, the fetch truncates and the
tool now reports `trend: null` (fixed 2026-07-03) rather than a
biased direction — correct, but it means busy instances lose the trend
entirely.

**Fix:** group by week via `client.aggregate_records` (already used for
`top_products`) instead of raw `search_read` + client-side bucketing. Removes
the truncation failure mode and cuts payload size. Watch for week-label
stability across Odoo major versions (the reason the original plan chose
client-side bucketing) before making the switch.

## FX conversion for mixed-currency totals

`sales_snapshot`, `receivables_health`, and `procurement_watch` currently
never convert currencies — they sum raw amounts and, when a business spans
more than one currency, add a `by_currency` breakdown plus a
`mixed_currencies` risk instead of a (potentially wrong) single total.

**Fix (only if a real multi-currency user needs a single blended number):**
pull rates from `res.currency.rate` and add an FX-converted total alongside
`by_currency`. Needs a documented "as-of rate" choice (today's rate vs. the
invoice's rate) since the two produce different — both defensible — numbers.

## Configurable verdict thresholds via env vars

`pipeline_review`, `sales_snapshot`, and `receivables_health` verdict
cut-offs (stalled %, growth %, overdue %) are now tool call parameters
(shipped 2026-07-03) instead of hardcoded, but every LLM-driven call still
needs to pass them explicitly to override the default.

**Fix (only if users ask to calibrate once per deployment rather than
per-call):** add `ODOO_*_THRESHOLD` env var defaults that the tool falls back
to when the caller doesn't pass a value, so a business can set its own
baseline once instead of relying on the LLM to remember non-default
thresholds every time.

## Smaller items

- `docs/tools.md`'s tool-groups table doesn't cross-link the "Analyst
  reports" section — pure polish.
