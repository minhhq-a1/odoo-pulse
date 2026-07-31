# Releasing odoo-pulse

The canonical maintainer procedure for publishing a release. `pyproject.toml`
holds the only authoritative version; every other manifest is generated from it.

Read this end to end before your first release. The order of the sections is the
order of the work.

## 1. Prerequisites and feature freeze

Before starting a release cycle:

- You have push access to `main` and can approve the protected `pypi`
  environment.
- `main == origin/main`, and `git status --short` is empty.
- PyPI Trusted Publishing is configured for `release.yml` / environment `pypi`.
- No Dependabot `github-actions` PR is open. Every action is pinned to a commit
  SHA, so an unmerged bump means the release publishes through stale — possibly
  unpatched — actions, including the one holding `id-token: write` against PyPI.
  Merge it now: once the release candidate is tagged, the freeze below forbids
  it, and the release runs on whatever was pinned at tag time.

From the moment a release candidate is tagged until the stable release is
published, the tree is frozen. No new tool, tool schema, report formula, query
policy, write policy, compatibility shim, or unrelated refactor lands. Only two
kinds of change are allowed: a fix for a blocker found while soaking, and a
factual documentation correction that cannot alter a published artifact.

## 2. Local fast preflight

Run from a clean checkout of the commit you intend to release:

```bash
python3 scripts/release/sync_version.py --check
python3 -m ruff check .
python3 -m pytest -q
git diff --check
git status --short
```

All five must be clean. Every tag also needs its own release notes — the
`validate` job asserts `docs/releases/<tag>.md` exists before it builds
anything, so a tag without notes cannot publish at all:

```bash
test -f "docs/releases/v1.9.0rc1.md"
```

Write and commit that file before tagging. A release candidate gets its own
note, not the stable one: it must say the moving Docker aliases are untouched
and that promotion is not guaranteed.

Then confirm the release identity the tag will have to match:

```bash
python3 scripts/release/release_contract.py identity --root . --tag v1.9.0rc1
```

This prints the four values the workflows consume and fails if the tag does not
exactly equal `v` plus the project version.

Build and check the distributions in a throwaway directory — never trust a
stale `dist/`, which may hold artifacts from older versions plus an MCPB bundle
that Twine correctly rejects as an unknown Python distribution:

```bash
DIST="$(mktemp -d)"
python3 -m build --outdir "$DIST"
python3 -m twine check "$DIST"/*.whl "$DIST"/*.tar.gz
```

## 3. Required remote evidence

Collect all four before tagging. Record every run URL.

| Evidence | Where | Requirement |
|---|---|---|
| Python matrix | `ci.yml`, job `test` | green on 3.10, 3.11, 3.12, 3.13 |
| MCP floor | `ci.yml`, job `mcp-floor` | green with `mcp[cli]==1.3.0`, surfaces 31/1 and 88/1 |
| Odoo playground | `playground.yml`, job `smoke` | green on Odoo 18 **and** Odoo 19 |
| Docker preflight | `docker.yml` | build and probe green with `push_image=false` |

`playground.yml` and `docker.yml` are manual. Dispatch them against the exact
commit you intend to tag and verify the run's `headSha` matches your local
`HEAD`:

```bash
gh workflow run playground.yml --ref main
gh workflow run docker.yml \
  -f release_ref="$(git rev-parse HEAD)" \
  -f version=1.9.0rc1 \
  -f push_image=false
gh run list --commit "$(git rev-parse HEAD)"
```

Use `git rev-parse HEAD` rather than a short SHA. `actions/checkout` only treats
a **full 40-character** SHA as a commit; an abbreviated one is read as a branch
or tag name, and the job fails inside checkout with an opaque
`git fetch … refs/heads/<short-sha>*` error after retrying for about a minute.

A `push_image=false` dispatch must never run the push job. Confirm that in the
run's job list before continuing.

## 4. Version mapping

One canonical version, four representations. The synchronizer is the only thing
that writes them.

| Target | Release candidate | Stable |
|---|---|---|
| `pyproject.toml` version | `1.9.0rc1` | `1.9.0` |
| `manifest.json` version | `1.9.0-rc.1` | `1.9.0` |
| `.claude-plugin/plugin.json` version | `1.9.0-rc.1` | `1.9.0` |
| `server.json` version | `1.9.0-rc.1` | `1.9.0` |
| `server.json` `packages[0].version` | `1.9.0rc1` | `1.9.0` |
| Git tag | `v1.9.0rc1` | `v1.9.0` |
| Release notes file | `docs/releases/v1.9.0rc1.md` | `docs/releases/v1.9.0.md` |
| Docker aliases | `1.9.0rc1` only | `1.9.0`, `1.9`, `1`, `latest` |

PEP 440 `1.9.0rc1` maps to SemVer `1.9.0-rc.1`. Only MCPB, the Claude plugin,
and the MCP server descriptor take SemVer; the PyPI package entry keeps the
canonical PEP 440 string because that is what pip resolves.

To change the version, edit `pyproject.toml` only, then:

```bash
python3 scripts/release/sync_version.py
python3 scripts/release/sync_version.py --check
pip install -e ".[dev]"
```

Reinstalling the editable package refreshes `importlib.metadata`. Skip it and a
stale `dist-info` directory will make `odoo_pulse.__version__` disagree with the
source you just edited.

### Docker alias safety

`docker.yml` derives aliases with `docker/metadata-action` using `type=pep440`,
which understands that `1.9.0rc1` is a prerelease and therefore withholds the
moving aliases. `scripts/release/release_contract.py check-docker-tags` then
fails the build unless the derived list is exactly the expected set.

`type=raw,value=latest` must never reappear in `docker.yml`. It is
unconditional, so it would retag `latest` onto a release candidate and silently
upgrade every user who tracks the moving alias. `type=semver` must not be used
either: it does not parse PEP 440 prereleases.

## 5. Ecosystem manifest validators

Run all three against the rendered manifests before the first tag of a cycle.
Record each tool's version alongside its exit code.

```bash
npm view @anthropic-ai/mcpb version
npx -y @anthropic-ai/mcpb validate manifest.json

claude --version
claude plugin validate .

mcp-publisher validate server.json
```

All three must exit zero. A rejection blocks the release. Never "fix" it by
reshaping the canonical version — correct the target representation instead.

## 6. Authorization boundary

**Every tag push and every remote publish command requires explicit human
authorization immediately before that step.** Approval to design the release,
to merge the machinery, or to publish an earlier candidate never carries
forward. Before each of these, stop and present the evidence, then wait:

- `git push origin main`
- `git tag` followed by `git push origin <tag>`
- approving the protected `pypi` environment
- `gh workflow run publish-mcp.yml`

Never push with `--tags`; push the one tag by name.

## 7. Publish the release candidate

With authorization granted, and `main == origin/main` fully green:

```bash
git tag -a v1.9.0rc1 -m "odoo-pulse 1.9.0rc1"
git show --no-patch --decorate v1.9.0rc1
test "$(git rev-list -n 1 v1.9.0rc1)" = "$(git rev-parse origin/main)"
git push origin v1.9.0rc1
```

`release.yml` then runs one sequential chain: validate, build once, PyPI,
Docker, GitHub Release. Approve the `pypi` environment only after validate and
build are green.

Verify from outside the checkout — a probe run inside the repository can import
the working tree instead of the published artifact:

```bash
VENV="$(mktemp -d)"; python3 -m venv "$VENV"
"$VENV/bin/pip" install "odoo-pulse==1.9.0rc1"
cd "$(mktemp -d)" && "$VENV/bin/python" -c \
  'from odoo_pulse import __version__; print(__version__)'

docker pull ghcr.io/minhhq-a1/odoo-pulse:1.9.0rc1
docker image inspect --format '{{index .RepoDigests 0}}' \
  ghcr.io/minhhq-a1/odoo-pulse:1.9.0rc1

gh release view v1.9.0rc1 --json isPrerelease,tagName,url
```

Require `isPrerelease` to be `true`, the default surface to be 31 tools and one
resource, and the complete surface to be 88 tools. Then confirm the candidate
did not disturb the stable channel: `latest` must still resolve to its pre-RC
digest, and `docker manifest inspect` must still fail for both the `1` and
`1.9` aliases.

Do not dispatch `publish-mcp.yml` for a release candidate. It will refuse.

## 8. The soak clock

A candidate must soak for at least **48 hours** before promotion.

- The clock starts at the timestamp of the **latest successful verification**,
  not at tag creation.
- Any change to runtime code, packaging, dependencies, or workflow behaviour
  that affects published content requires a new candidate (`rcN+1`) and restarts
  the clock from zero.
- A documentation-only correction that cannot affect an artifact does not reset
  the clock, but record the reasoning explicitly.
- The clock must be 48 uninterrupted hours. An open Critical or Important
  release issue pauses promotion regardless of elapsed time.

At the 48-hour mark, re-run the external probes from section 7 and the Odoo
18/19 playground before promoting.

## 9. Promote to stable

Start the promotion worktree from the **soaked candidate's commit**, not from a
newer `main`. Change `pyproject.toml` to `1.9.0`, synchronize, and prove the
runtime is byte-identical to what you soaked:

```bash
git diff --exit-code v1.9.0rc1 -- src/ tests/
```

Any difference there means you would be publishing unsoaked code: stop and cut
a new candidate instead. Then run section 2 and section 5 again, merge, push
with authorization, and require every gate in section 3 green on the exact final
commit.

Tag and push `v1.9.0`, watch the same sequential chain, and verify PyPI, `uvx`,
and GHCR from outside the repository. All four stable aliases — `1.9.0`, `1.9`,
`1`, and `latest` — must resolve to the same digest.

**The MCP Registry is last.** Its ownership check reads the `mcp-name` marker
from the published PyPI package, so it can only succeed after PyPI is live.
With separate authorization:

```bash
gh workflow run publish-mcp.yml -f release_ref=v1.9.0
```

That workflow refuses a prerelease ref, refuses drifted manifests, validates
`server.json`, and confirms the exact version is live on PyPI — all before it
mints an OIDC credential.

### Optional Smithery mirror

Smithery is a non-blocking post-release mirror. Synchronize it only after all
first-party channels above are verified, and only with explicit owner access:

```bash
SMITHERY_API_KEY=<key> ./scripts/release/publish_smithery.sh
```

The helper validates the MCPB version before upload, captures the deployment id
returned by Smithery, and requires that exact deployment to reach `SUCCESS` in
the authenticated releases API. It exits non-zero when the deployment cannot
be verified. The public `/servers/<qualified-name>` payload has no version
field, so schema shape or version-string grep is not valid publication proof.

## 10. Per-channel retry

Each channel is independent and idempotent only in the direction of "already
done". When one fails, fix forward on that channel alone.

| Failed channel | Retry |
|---|---|
| validate or build | Fix the source, cut a new candidate. Never re-point the tag. |
| PyPI | Re-run the job. A duplicate filename is a provenance failure, not a no-op — investigate, do not force. |
| Docker | Re-run `docker.yml` at the tag with `push_image=true`. The build is deterministic and the probe gates the push. |
| GitHub Release | Re-run `release-record`. `gh release create` is not idempotent, so if the release was partially created, delete the incomplete *release* first (`gh release delete <tag>` — this does not touch the tag) or upload the assets with `gh release upload <tag> --clobber`. |
| MCP Registry | Re-dispatch `publish-mcp.yml` with the same `release_ref` once PyPI is confirmed live. |

Only re-run a downstream channel when the source at the tag is unchanged. If the
source must change, the tag is finished — cut the next version.

## 11. Tags and artifacts are immutable

**Do not move or recreate a release tag.** Never delete, re-point, or
force-push one, and never re-upload a published artifact under a filename that
already exists. A tag is a permanent claim about which commit produced which
published bytes; breaking it destroys the provenance chain that every downstream
verification depends on, and consumers who already resolved the old tag will
silently diverge from those who resolve it later.

If a tagged commit turns out to be wrong, the answer is always a new version.

## 12. Incident response after a stable release

For a defect found in a published stable release, in order of preference:

1. **Fix forward.** Cut `v1.9.1` through this same procedure, including a
   candidate and soak if the fix touches runtime behaviour. This is the default.
2. **Roll back the moving aliases.** If `v1.9.0` is actively harmful, re-point
   `latest`, `1`, and `1.9` at the last good release by re-running `docker.yml`
   against that tag. The exact version alias `1.9.0` stays where it is.
3. **Yank on PyPI.** Yanking hides the version from new resolutions while
   leaving pinned installs working. Prefer it to deletion, which breaks
   reproducibility permanently. Then publish `v1.9.1`.

Document the incident, the affected channels, and the remediation in
`docs/releases/`. Announce the superseding version rather than quietly
retagging.
