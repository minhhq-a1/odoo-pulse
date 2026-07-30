#!/usr/bin/env bash
# Publish the odoo-pulse MCPB bundle to Smithery and verify the live config
# picked up the new version.
#
# Usage:
#   export SMITHERY_API_KEY=sk-...          # your Smithery API key
#   ./scripts/release/publish_smithery.sh           # uses dist/odoo-pulse-<pyproject version>.mcpb
#
# The key is read from the environment only — never hardcode it or commit it.
set -euo pipefail

QUALIFIED_NAME="minhhq/odoo-pulse"
# Use api.smithery.ai — it reflects a new publish within seconds.
# (registry.smithery.ai serves a heavily-cached view that can lag for minutes.)
REGISTRY_API="https://api.smithery.ai/servers/${QUALIFIED_NAME}"
# The /servers response is a config-schema payload with no version field at
# all, so no string match against it can ever confirm a version. /releases
# (authenticated) lists each publish by deployment id and status instead.
RELEASES_API="${REGISTRY_API}/releases"

cd "$(dirname "$0")/../.."

# ---- 0. Preconditions -------------------------------------------------------
if [[ -z "${SMITHERY_API_KEY:-}" ]]; then
  echo "ERROR: SMITHERY_API_KEY is not set. Run: export SMITHERY_API_KEY=sk-..." >&2
  exit 1
fi

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
BUNDLE="dist/odoo-pulse-${VERSION}.mcpb"
echo "==> Target version: ${VERSION}"

# ---- 1. Ensure the bundle exists and matches the version --------------------
if [[ ! -f "$BUNDLE" ]]; then
  echo "==> ${BUNDLE} missing; packing a fresh bundle from manifest.json"
  PACKDIR="$(mktemp -d)"
  cp manifest.json icon.png "$PACKDIR"/
  npx -y @anthropic-ai/mcpb validate "$PACKDIR/manifest.json"
  ( cd "$PACKDIR" && npx -y @anthropic-ai/mcpb pack . "odoo-pulse-${VERSION}.mcpb" )
  mkdir -p dist
  cp "$PACKDIR/odoo-pulse-${VERSION}.mcpb" "$BUNDLE"
  rm -rf "$PACKDIR"
fi

BUNDLE_VER="$(unzip -p "$BUNDLE" manifest.json | python3 -c "import json,sys; print(json.load(sys.stdin)['version'])")"
if [[ "$BUNDLE_VER" != "$VERSION" ]]; then
  echo "ERROR: ${BUNDLE} declares ${BUNDLE_VER}, expected ${VERSION}. Re-pack it." >&2
  exit 1
fi
echo "==> Bundle OK: ${BUNDLE} (manifest version ${BUNDLE_VER})"

# ---- 2. Publish -------------------------------------------------------------
echo "==> Publishing to Smithery as ${QUALIFIED_NAME}"
PUBLISH_OUTPUT="$(npx -y @smithery/cli mcp publish "$BUNDLE" -n "$QUALIFIED_NAME")"
echo "$PUBLISH_OUTPUT"

DEPLOYMENT_ID="$(echo "$PUBLISH_OUTPUT" | grep -o '"deploymentId":"[^"]*"' | head -1 | cut -d'"' -f4)"
if [[ -z "$DEPLOYMENT_ID" ]]; then
  echo "ERROR: could not parse deploymentId out of the publish output above." >&2
  exit 1
fi
echo "==> Published deployment: ${DEPLOYMENT_ID}"

# ---- 3. Verify the live registry serves THIS deployment ---------------------
# Match on the deployment id the publish call just returned, not on a version
# string: /releases lists deployments by id/status, never by version, and a
# version match against /servers can't work (see RELEASES_API comment above).
echo "==> Verifying deployment ${DEPLOYMENT_ID} (version ${VERSION}) is live (allowing a few seconds to propagate)"
for attempt in 1 2 3 4 5 6; do
  sleep 5
  STATUS="$(curl -sf -H "Authorization: Bearer ${SMITHERY_API_KEY}" "$RELEASES_API" \
    | DEPLOYMENT_ID="$DEPLOYMENT_ID" python3 -c "
import json, os, sys
target = os.environ['DEPLOYMENT_ID']
data = json.load(sys.stdin)
for r in data.get('releases', []):
    if r.get('id') == target:
        print(r.get('status', ''))
        break
" 2>/dev/null || true)"
  if [[ "$STATUS" == "SUCCESS" ]]; then
    echo "==> VERIFIED: deployment ${DEPLOYMENT_ID} (version ${VERSION}) is live with status SUCCESS."
    exit 0
  fi
  echo "    attempt ${attempt}: deployment status='${STATUS:-not found yet}'..."
done

echo "WARNING: publish command succeeded, but ${RELEASES_API} has not reported" >&2
echo "         deployment ${DEPLOYMENT_ID} (version ${VERSION}) as SUCCESS yet. This is NOT" >&2
echo "         a confirmation that ${VERSION} is live; treat the mirror as unverified until it is." >&2
echo "         Re-check: curl -s -H \"Authorization: Bearer \$SMITHERY_API_KEY\" ${RELEASES_API} | python3 -m json.tool" >&2
exit 0
