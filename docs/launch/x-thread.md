# X/LinkedIn thread (5 posts)

1/ Your ERP knows if your business is healthy. It just can't tell you.
I built odoo-pulse: an open-source AI business analyst for @Odoo, over MCP.
Ask "how's the company doing?" → one call → verdict. [demo GIF]

2/ Every tool answers a whole management question: business_pulse
(morning briefing), pipeline_review (stalled deals), receivables_health
(AR aging), inventory_risk (shortages + dead stock), absence_overview...

3/ Design bet: composed reports with verdicts beat CRUD wrappers.
The server does the analysis; the model narrates. Fewer round-trips,
no context bloat, answers a CFO can read.

4/ Safety: read-only by default. Writes need FOUR independent opt-ins.
System models are never writable. Mixed currencies are flagged, never
silently summed.

5/ MIT. Works on Odoo Online/sh/on-premise (18+), nothing installed
inside Odoo. Try it with the seeded docker playground (first boot pulls
~4GB of images, allow a few minutes):
https://github.com/minhhq-a1/odoo-pulse  ⭐ if it's useful!
