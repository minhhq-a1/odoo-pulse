# Plan: 2026-07-15 project-review findings

Work plan for the findings from the 2026-07-15 full-project review.
Ordered by (impact / risk); every task ends with the full suite green
(`pytest -q`, 382+ tests) and is committed separately so any step can be
reverted alone. No task changes the write-safety chain.

Finding → task map:

| # | Finding | Task | Size |
|---|---------|------|------|
| 1 | `__init__.__version__` = 0.1.0 vs 1.7.0 everywhere else | T1 | S |
| 2 | `list_models` silently capped at `ODOO_MAX_RECORDS` | T2 | S |
| 3 | No HTTP keep-alive: fresh transport per RPC | T3 | M |
| 4 | Pretty-printed JSON inflates token cost | T4 | S |
| 5 | `search_read` without `fields` can return binary blobs | T5 | S |
| 6 | CI has no lint / type-check / coverage; matrix stops at 3.12 | T6 | M |
| 7 | Bool env parsing inconsistent, no strip | T7 | S |
| 8 | `FakeClient` signatures can drift from `OdooClient` | T8 | S |
| 9 | Repeated m2o / truncation-risk boilerplate in report tools | T9 | L |
| 10 | `timezone_offset` hardcoded default 7, int-only | T10 | M |
| 11 | `sales_snapshot` trend truncates on busy instances (roadmap) | T11 | M |
| 12 | Docker runs as root; `.env.example` says "27 tools" | T12 | S |

Suggested batches: **Batch A** = T1+T2+T7+T12 (quick fixes),
**Batch B** = T3+T4+T5 (performance), **Batch C** = T6+T8 (tooling),
**Batch D** = T9+T10+T11 (refactor + roadmap item).

---

## T1 — Single-source the version

**Files:** `odoo_pulse/__init__.py`, `pyproject.toml` (dev extras),
new `tests/test_metadata.py`.

- `__init__.py`: replace the hardcoded string with
  `importlib.metadata.version("odoo-pulse")`, guarded by
  `PackageNotFoundError` → `"0.0.0+unknown"` (source tree without install).
- New `tests/test_metadata.py`: read the version from `pyproject.toml`
  (`tomllib` on 3.11+, `tomli` on 3.10 — add `tomli; python_version<'3.11'`
  to the `dev` extra) and assert it matches:
  - `odoo_pulse.__version__`
  - `server.json` (both `version` fields)
  - `manifest.json`
  - `.claude-plugin/plugin.json`

**Done when:** bumping only `pyproject.toml` makes the test fail listing
every stale file; release checklist no longer relies on memory.

## T2 — `list_models` must not truncate silently

**Files:** `odoo_pulse/odoo_client.py` (`list_models`), `tests/test_client.py`.

`ir.model` on a stock instance has 500–1000+ rows; the current single
`search_read` caps at `ODOO_MAX_RECORDS` (200) with no signal.

- Paginate internally: loop `search_read(..., limit=cap, offset=n*cap)`
  until a page comes back shorter than the cap, with a hard ceiling of
  25 pages (5 000 models) as a runaway guard.
- Return the combined list — the public return type (list of
  `{model, name}`) does not change, so `tools_generic.list_models` and its
  tests are untouched.

**Tests:** stub `execute_kw` to serve two full pages then a short one;
assert the offsets requested and the concatenated result. One test for the
runaway ceiling.

## T3 — HTTP keep-alive via thread-local proxies

**Files:** `odoo_pulse/odoo_client.py`, `tests/test_client.py`.

`_proxy()` builds a fresh `ServerProxy` + `Transport` per call, so every
RPC pays a new TCP + TLS handshake. `xmlrpc.client.Transport` caches its
HTTP connection and the stdlib already retries once on a stale keep-alive
connection (`Transport.request` catches `RemoteDisconnected` /
`ECONNRESET`), so reuse is safe — the only constraint is that a proxy must
not be shared across threads (`gather` runs up to 8 workers).

- Add `self._local = threading.local()` in `__init__`.
- `_proxy(path)`: look up `self._local.proxies` (a `dict[str, ServerProxy]`,
  created on first access), build-and-store on miss, return the cached
  proxy per endpoint path. Each `gather` worker thread gets its own pair
  of proxies; sequential calls inside a report reuse the connection.
- `_ssl_context` stays a shared `cached_property` (an `SSLContext` is
  thread-safe for handshakes).

**Tests:** same object returned for repeated `_proxy("/xmlrpc/2/object")`
calls on one thread; different objects across two threads (run a thunk in
`ThreadPoolExecutor` and compare ids). No network needed.

**Risk note:** long-idle sessions may hold a dead socket; covered by the
stdlib single retry. Do not add our own retry loop here (see T-deferred).

## T4 — Compact JSON output (token cost)

**Files:** `odoo_pulse/runtime.py`, `odoo_pulse/tools_workflows.py`
(standup error path), `.env.example`, `README.md`,
`tests/test_runtime.py`.

Tool output goes straight into the calling LLM's context window;
`indent=2` adds ~15–30 % tokens on large payloads.

- Add a module-level `dumps(obj)` helper in `runtime.py`: reads
  `ODOO_JSON_INDENT` (default `"2"` — behaviour unchanged); `0` or
  `compact` → `json.dumps(obj, ensure_ascii=False, separators=(",", ":"),
  default=str)`.
- `safe()` and the `standup_digest` local error path both call `dumps`.
- Document the env var in `.env.example` and README, recommending
  `ODOO_JSON_INDENT=0` for production use. (Flipping the default to
  compact is a candidate for the next major bump, not this change.)

**Tests:** with the env var set (monkeypatch), `safe(lambda: {...})`
contains no newline; without it, output is unchanged (existing tests
already pin the indented shape).

## T5 — Guard `search_read` against binary payloads

**Files:** `odoo_pulse/tools_generic.py`, `tests/test_tools_smoke.py`
(or a new test file).

When the caller omits `fields`, Odoo returns every readable field,
including base64 `binary` columns. Use Odoo's native guard instead of
filtering fields client-side:

- In the `search_read` tool, when `fields` is falsy, pass
  `context={"bin_size": True}` to `client.search_read` — binary fields
  then come back as human-readable sizes (`"2.5 Kb"`), never blobs.
  Explicit `fields` requests are untouched (callers wanting actual binary
  content should use `read_attachment`).
- Extend the docstring: "omitting `fields` returns all fields with binary
  columns replaced by their size; request binary content via
  read_attachment".

**Tests:** assert the recorded call carries the `bin_size` context when
`fields` is omitted and no context when fields are given.

## T6 — CI: lint, types, coverage, modern Python matrix

**Files:** `pyproject.toml`, `.github/workflows/ci.yml`,
plus whatever small fixes ruff/mypy surface.

- Dev extras become
  `dev = ["pytest>=7.0", "pytest-cov", "ruff", "mypy", "tomli; python_version<'3.11'"]`.
- `[tool.ruff]`: `line-length = 100`, `lint.select = ["E", "F", "I", "UP", "B"]`
  (lint only — do NOT enable `ruff format --check`; the codebase has its
  own hand-formatted style and reformatting is a separate, optional,
  whole-repo commit).
- `[tool.mypy]`: `python_version = "3.10"`, run against `odoo_pulse/` only,
  `ignore_missing_imports = true` pragmatically for `mcp`/`dotenv`;
  tighten later.
- CI job steps: `ruff check .` → `mypy odoo_pulse` → `pytest --cov=odoo_pulse
  --cov-fail-under=<measured − 2 %>` (measure actual coverage first, set the
  floor just below it, raise over time).
- Matrix: add `"3.13"` and `"3.14"`; add both classifiers in
  `pyproject.toml`.

**Done when:** CI is green on 3.10–3.14 with all three gates active. Fix
whatever ruff/mypy find in the same PR, one commit per category of fix.

## T7 — Unify boolean env parsing

**Files:** `odoo_pulse/odoo_client.py`, `tests/test_config.py`.

- Add `_bool_env(name: str, default: bool) -> bool` beside `_int_env` /
  `_float_env`: strip + lower; `{"1","true","yes","on"}` → True,
  `{"0","false","no","off"}` → False, empty → default, anything else →
  `OdooConfigError` (fail-loud, matching `_int_env`).
- Use it for `ODOO_READ_ONLY`, `ODOO_VERIFY_SSL`, `ODOO_ALLOW_DELETE`.

**Behaviour change (accepted):** garbage like `ODOO_ALLOW_DELETE="ture"`
now fails at startup instead of silently resolving; trailing whitespace
now parses. Both are strictly safer. Tests cover the new strings and the
error case.

## T8 — Pin the FakeClient contract

**Files:** `tests/conftest.py`, new `tests/test_fake_contract.py`.

- Fix the one known drift: `FakeClient.fields_get` gains the
  `refresh: bool = False` keyword (ignored).
- New contract test: for every public method `FakeClient` shares with
  `OdooClient` (`search_read`, `search_count`, `read`, `fields_get`,
  `execute_kw`, `create`, `write`, `unlink`, `aggregate_records`,
  `list_models`, `version`, `major_version`), assert
  `inspect.signature` parameter names and defaults match (allow the fake
  to differ only in annotations). This turns future client-signature
  changes into an immediate test failure instead of a silent fake drift.

## T9 — Deduplicate report boilerplate

**Files:** `odoo_pulse/workflow_helpers.py`, then one commit per report
module (`tools_reports_sales`, `_finance`, `_inventory`, `_hr`, `_ops`,
`_pulse`, `_projects`, `tools_workflows`), touching their tests only where
exact strings are pinned.

New helpers (added with their own unit tests in
`tests/test_workflow_helpers.py` **before** any call-site migration):

- `m2o_id(row, field) -> int | None` and
  `m2o_name(row, field, default=None) -> str | None` — replace the
  ubiquitous `row["x"][0]` / `row["x"][1] if row.get("x") else None`.
- `truncation_risk(truncation, noun, *, detail=None) -> dict` — builds the
  `{"code": "truncated_data", "count": missing, "message": ...}` dict with
  one standard wording (`"Report covers only {fetched} of
  {total_matching} matching {noun}(s); {detail}"`).
- `apply_truncation(summary, truncation, *, prefix="") -> None` — sets
  `summary["truncated"] / ["total_matching"]`
  (or `{prefix}_truncated` / `total_{prefix}_matching`).

Migration rules:

- Where a test pins today's message text, either keep the old string via
  the `detail` parameter or update the test in the same commit — never
  loosen an assertion to `assert "truncated" in ...`.
- Custom-coded risks (`truncated_budget_lines`, `truncated_trend`,
  `truncated_milestone_data`) keep their codes; only the dict construction
  goes through the helper (add a `code=` override parameter).
- Do not refactor verdict/rank sorting in this pass — the rank dicts
  differ per tool (`n/a` handling) and unifying them buys little.

**Done when:** `grep -n '\[1\] if .*get(' odoo_pulse/tools_*` returns
nothing and every `truncated_data` risk goes through the helper.

## T10 — Configurable default timezone, fractional offsets

**Files:** `odoo_pulse/workflow_helpers.py`, every tool module with
`timezone_offset` parameters, `.env.example`, `README.md`,
`tests/test_workflow_helpers.py`.

- `workflow_helpers.default_tz_offset() -> float`: reads
  `ODOO_DEFAULT_TZ_OFFSET` (float, e.g. `5.5`), default `7.0` (unchanged
  behaviour for existing deployments).
- Tool signatures change from `timezone_offset: int = 7` to
  `timezone_offset: float | None = None`; first line of each `run()`
  resolves `tz = default_tz_offset() if timezone_offset is None else
  timezone_offset`. `today_in_tz` / `parse_when` / `utc_bound` already
  work with floats (`timedelta(hours=5.5)`).
- Docstrings: "UTC offset in hours (supports halves, e.g. 5.5); defaults
  to ODOO_DEFAULT_TZ_OFFSET or +7".

**Tests:** env-var fallback, explicit-arg precedence, one half-hour-offset
case through `utc_bound` (`5.5` → `18:30:00` boundary).

## T11 — Trend series without the 200-row cliff (roadmap item)

**Files:** `odoo_pulse/tools_reports_sales.py`,
`tests/test_tools_reports_sales.py`, `docs/roadmap.md` (close the entry).

The roadmap's own caveat stands: server-side `date_order:week` group
labels are not stable across Odoo majors (localised strings on ≤18,
ISO-ish on 19+), which is why bucketing stayed client-side. Pragmatic fix
that removes the failure mode without the label problem:

- Paginate `trend_fetch` (same offset loop as T2) up to a hard cap of
  5 pages × `max_records` (1 000 orders, fields are just
  `id, amount_total, date_order` — a small payload). Only past that cap
  does the existing `trend: null` + `truncated_trend` risk fire.
- Keep the server-side `formatted_read_group` week aggregate as a
  follow-up roadmap note gated on Odoo 19+ only.

**Tests:** three-page fake sequence buckets correctly; cap exceeded still
degrades to `trend: null` with the risk attached.

## T12 — Small fixes

**Files:** `Dockerfile`, `.env.example`.

- Dockerfile: add a non-root user after `pip install`
  (`RUN useradd -r app` + `USER app`) — stdio server needs no privileges.
- `.env.example`: "27 tools" → "28 tools"; add the new env vars from this
  plan (`ODOO_JSON_INDENT`, `ODOO_DEFAULT_TZ_OFFSET`) with comments.

## Deferred (explicitly not in this plan)

- **Retry/backoff on transient network errors** — the stdlib transport
  retry (T3) covers the common stale-connection case; a full retry layer
  needs idempotency bookkeeping and real-world evidence first.
- **FX conversion for mixed-currency totals** — stays on the roadmap;
  needs a user with the requirement to pick the as-of-rate semantics.
- **Repo-wide `ruff format`** — optional one-shot commit after T6, only
  if the maintainer wants machine formatting.

## Verification per batch

1. `pytest -q` green (grows past 382 as tasks add tests).
2. After T6: `ruff check .` and `mypy odoo_pulse` green locally and in CI.
3. Batch B ideally gets one manual pass against a live instance
   (`python scripts/smoke_live.py`) or the Docker playground
   (`make playground-smoke`) to confirm keep-alive and `bin_size` behave
   on real Odoo.
