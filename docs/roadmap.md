# Roadmap

Follow-up work deferred from the 2026-07 analyst-gap closure
(`docs/superpowers/plans/2026-07-03-analyst-gaps.md`). Nothing here is
scheduled — pick items up when a real need appears.

## Trend bucketing: server-side on Odoo 19+ (follow-up)

`sales_snapshot`'s `weekly_revenue` trend now pages through the confirmed
orders in the window (up to 5 x `ODOO_MAX_RECORDS`, ~1 000 orders, three
small fields per row) instead of the old single 200-row fetch, so ordinary
busy instances keep their trend. Past that budget it still reports
`trend: null` with a `truncated_trend` risk rather than a biased direction.

**Remaining work (only for instances beyond ~1 000 orders per window):**
group by week via `client.aggregate_records` (as `top_products` already
does). Week labels from `read_group` are localised strings on Odoo <= 18 but
ISO-style on 19+, which is why bucketing stayed client-side; a version-gated
server-side path for 19+ only would remove the cap there without risking
label parsing on older majors.

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
