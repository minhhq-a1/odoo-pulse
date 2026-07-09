# r/ClaudeAI + r/mcp post (same text, adjust flair)

**Title:** MCP server design lesson: stop wrapping CRUD, wrap *questions* —
I built an AI business analyst for Odoo ERP

**Body:**

Most ERP MCP servers expose search/read/write tools and let the model
compose them. That works, but burns context and round-trips, and the model
re-derives "what does healthy look like?" every time.

odoo-pulse takes the opposite bet: one tool = one management question,
answered server-side in a single call — numbers + highlights + risks + a
verdict the model can quote directly. `business_pulse` gives a whole
company briefing in one tool call. 322 tests, read-only by default,
playground included so you can demo without an Odoo account.

Repo (MIT): https://github.com/minhhq-a1/odoo-pulse

Curious whether others building MCP servers have landed on the same
pattern — "composed report tools" beat "thin wrappers" hard in our usage.
