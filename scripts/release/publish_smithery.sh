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
npx -y @smithery/cli mcp publish "$BUNDLE" -n "$QUALIFIED_NAME"

# ---- 3. Verify the live registry serves THIS version ------------------------
# Look for the exact version string. A schema-shape marker cannot be used here:
# every field of this bundle also exists in the previously published one, so a
# shape check would match the stale entry and report a false success.
echo "==> Verifying live registry reports ${VERSION} (allowing a few seconds to propagate)"
for attempt in 1 2 3 4 5 6; do
  sleep 5
  if curl -sf "$REGISTRY_API" | grep -q "\"${VERSION}\""; then
    echo "==> VERIFIED: live Smithery entry reports version ${VERSION}."
    exit 0
  fi
  echo "    attempt ${attempt}: ${VERSION} not visible yet..."
done

echo "WARNING: publish command succeeded, but the registry API has not reported" >&2
echo "         version ${VERSION} yet. This is NOT a confirmation that ${VERSION}" >&2
echo "         is live; treat the mirror as unverified until it is." >&2
echo "         Re-check: curl -s ${REGISTRY_API} | python3 -m json.tool | grep -i version" >&2
exit 0
