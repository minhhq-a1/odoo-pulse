# dev.to article — "CRUD bridges are a commodity. Build the analytics layer."

**Publish:** launch day, cross-link from HN comment if relevant.

**Outline:**
1. Intro (below) — the six-dashboards problem.
2. Why "one tool = one question" beats thin wrappers for LLMs
   (context cost, round-trips, verdict consistency) — with the
   build_report envelope as code example.
3. The safety story: four-layer write guard, read-only default.
4. Odoo-version reality: schema-conditional fields (mobile gone in 19), read_group vs formatted_read_group dispatch.
5. The playground trick: seeded demo data "with a story to tell" as a
   growth asset — your README demo is only as good as its data.
6. What's next: JSON-2 transport for Odoo 19+, scheduled digests.

**Intro draft:**

Ask any manager at a company running an ERP what they want from it and
you will not hear "a faster way to update records". You'll hear a
question: how are we doing? Are we going to make this quarter? Who's
blocked? The data is all there — spread across six modules and a dozen
dashboards. [continue on publish day]
