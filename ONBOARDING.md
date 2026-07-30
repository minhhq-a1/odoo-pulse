# odoo-pulse — Release Runbook (worked example: v1.9.0)

This walks a new maintainer through how a release actually happened in this
repo, using the v1.9.0 stable promotion as the concrete example. The
timeless, version-agnostic procedure lives in
[`docs/guides/releasing.md`](docs/guides/releasing.md) — read that first for
the *why* behind each step. This document shows the *what actually ran*:
real commits, real run URLs, real numbers, in the order they happened.

Full durable evidence: [`docs/releases/v1.9.0-evidence.md`](docs/releases/v1.9.0-evidence.md).

## The shape of a release

One canonical version lives in `pyproject.toml`. Everything else —
`manifest.json`, `.claude-plugin/plugin.json`, `server.json` — is generated
from it by `scripts/release/sync_version.py`. A release moves through five
stages, each gated before the next starts:

```
harden pipeline → cut RC → soak RC (≥48h) → promote to final → publish + MCP Registry → record evidence
```

Every tag push and every remote publish command needs **explicit human
authorization immediately before that step** — approval never carries
forward from an earlier step. This ran true in practice: the tag push, the
`v1.9.0` publish, and the MCP Registry dispatch were each their own
stop-and-ask.

## What happened for v1.9.0, in order

### 1. Hardening merged first (Tasks 1–9 of the release plan)

The release machinery itself (`release_contract.py`, `sync_version.py`,
`docker.yml`, `release.yml`, `publish-mcp.yml`, the runbook) was built,
tested, and merged to `main` **before** any version number changed. Nothing
about `1.9.0` existed yet — this step only hardens the pipeline that will
publish it.

### 2. RC prepared and published: `v1.9.0rc1`

- `pyproject.toml` → `1.9.0rc1`; `sync_version.py` mapped it to SemVer
  `1.9.0-rc.1` for the plugin/manifest/server descriptors and kept PEP 440
  `1.9.0rc1` for the PyPI package field.
- Local gate green, all three ecosystem validators (MCPB, Claude plugin,
  MCP Publisher) green.
- Tag `v1.9.0rc1` created on commit `90ff8517757d59ce03d50e39a07cd31a783bf55d`
  (tag object `dcc5e59a5c7e6530f40023d1f77b1023014fdb99`), pushed only after
  explicit authorization.
- `release.yml` ran its one sequential chain — validate → build → PyPI →
  Docker → GitHub Release — and published the RC as a **prerelease**. GHCR
  got only the exact `1.9.0rc1` tag; no moving alias (`latest`, `1`, `1.9`)
  was touched.

### 3. Soak

Target was 48 uninterrupted hours. The actual soak was **41h19m08s**
(`2026-07-28T09:12:52Z` → `2026-07-30T02:32:00Z`) — an **owner-approved
deviation**, recorded verbatim rather than rounded up or padded. A separate
scheduled `playground-smoke` cron run completed at `2026-07-30T05:48:16Z`
(after the soak window) as **post-soak verification only**; it was not used
to retroactively extend the soak duration. No Critical/Important blocker
surfaced, so no `rc2` cycle was needed.

This is the one place the worked example deviated from the written
procedure — and it shows the right way to handle a deviation: get explicit
owner sign-off, write the actual numbers down, and don't blur the two facts
(soak window vs. post-soak check) into one.

### 4. Promoted to final in an isolated worktree

- New worktree from the **soaked RC's tag commit** (never from a newer
  `main` that might have drifted).
- `pyproject.toml` → `1.9.0`; `sync_version.py` mapped every representation
  to plain `1.9.0` (RC's SemVer prerelease suffix drops entirely for stable).
- `pip install -e ".[dev]"` re-run so `importlib.metadata` didn't report a
  stale RC version.
- **Proved no runtime drift** before touching anything else:
  `git diff --exit-code v1.9.0rc1 -- src/ tests/` — clean. This is the load-bearing
  check: it's what lets you promote the *exact bytes you soaked*, not a
  respin.
- Full local gate: 663 tests passed, Ruff clean, wheel/sdist built fresh and
  passed Twine, clean-wheel probes hit 31/1 (default groups) and 88/1 (all
  groups).
- Diff from RC to final commit: **4 files, 5 lines, version metadata only.**
  That tight a diff is the actual proof the promotion didn't sneak in a
  behavior change.
- Committed `chore(release): prepare 1.9.0`, merged to `main`, pushed only
  after authorization, then required Python 3.10–3.13, the MCP floor, Odoo
  18 **and** 19, and a `push_image=false` Docker preflight all green on that
  exact commit (`a32f6d99baab3bc1006742ee7199b75c1f66276b`) before going
  anywhere near a tag.

### 5. Tagged and published: `v1.9.0`

- Preflight evidence presented, authorization asked and given, **then**:
  `git tag -a v1.9.0 -m "odoo-pulse 1.9.0"` on `a32f6d9`, verified it points
  at `origin/main`, pushed the tag alone (never `--tags`).
- `release.yml`'s tag trigger ran the full chain automatically: validate →
  build → publish-pypi → docker (build-probe → push_image) → release-record.
  All green.
- Verified from *outside* the repo, in fresh environments, so nothing could
  accidentally import the working tree instead of the published artifact:
  - `pip install odoo-pulse==1.9.0` in a scratch venv → version, 31/1, 88/1.
  - `uv run --with odoo-pulse==1.9.0` (uvx-style ephemeral env) → same.
  - `docker pull ghcr.io/minhhq-a1/odoo-pulse:1.9.0` → probe 31/1, and all
    four stable aliases (`1.9.0`, `1.9`, `1`, `latest`) resolved to the
    **identical digest** (`sha256:98867ad5...`).
  - `gh release view v1.9.0 --json isPrerelease` → `false`; wheel, sdist,
    and `SHA256SUMS.txt` attached; `releases/latest` → `v1.9.0`.
- **MCP Registry was last, and got its own separate authorization ask**
  (`gh workflow run publish-mcp.yml -f release_ref=v1.9.0`), because that
  workflow's ownership check only succeeds once PyPI is already live.
  Verified externally afterward against the public registry API:
  `io.github.minhhq-a1/odoo-pulse` version `1.9.0`, `isLatest: true`,
  `status: active`.

### 6. Evidence recorded, release closed

`docs/releases/v1.9.0-evidence.md` captured every hash, digest, run URL, and
the soak-deviation explanation with no placeholders — written and committed
*after* all four first-party channels were independently re-verified, not
copied from earlier draft notes. That commit was pushed only after its own
authorization ask, and a final fresh run of the full Completion Gate
Summary (`sync_version.py --check`, Ruff, `pytest -q`, whitespace, ref
equality, tag-ancestor check, plus the sixteen frozen MCP fingerprint
tests) confirmed everything held.

One explicitly non-blocking item was deferred rather than done inline: the
Smithery/Claude mirror sync (`scripts/release/publish_smithery.sh`) is a
documented post-release follow-up per the release spec — third-party mirrors
never gate a first-party stable release.

## Takeaways for the next release

- **Authorization is per-action, not per-conversation.** A tag push and a
  registry publish each got their own explicit ask, even within the same
  session, even after earlier steps were approved.
- **Prove the negative before promoting.** `git diff --exit-code <rc-tag> --
  src/ tests/` is what makes "we promoted the soaked bytes" a checked fact
  instead of a claim.
- **Record deviations exactly, don't normalize them.** 41h19m08s was written
  down as 41h19m08s, with the reason, not rounded to "≥48h" or padded with
  an unrelated cron run.
- **Verify from outside the repo.** Every install/pull check ran from a
  fresh venv, an ephemeral `uvx`-style environment, or a plain `docker
  pull` — never from inside the checkout, where a probe could accidentally
  exercise the working tree instead of the published artifact.
- **Third-party mirrors don't block.** Smithery/Claude marketplace sync is
  real follow-up work, tracked separately, and does not hold up the
  first-party channels (PyPI, GHCR, GitHub Release, MCP Registry).
