#!/usr/bin/env bash
#
# Lint a generated OpenAPI schema with the real Spectral CLI, using VTEX's own
# ruleset from the openapi-schemas repository.
#
# The ruleset cannot be vendored: it declares two custom JavaScript functions
# (definedNotExample, noChainedRefsInComponents) that Spectral resolves from a
# `functions/` directory next to the ruleset file. Pointing at the repository
# copy also means the rules never drift from the ones the VTEX pipeline runs.
#
# Usage:
#   validate.sh path/to/schema.json
#
# Environment:
#   OPENAPI_SCHEMAS_REPO  path to the openapi-schemas checkout (skips the search)
#   SPECTRAL_FORMAT       spectral output format (default: stylish, use json to parse)
#
# Exit codes:
#   0  no errors (warnings may still be reported)
#   1  at least one error-severity violation
#   2  bad usage, or the ruleset could not be located
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: validate.sh path/to/schema.json" >&2
  exit 2
fi

schema="$1"
if [[ ! -f "$schema" ]]; then
  echo "validate.sh: no such file: $schema" >&2
  exit 2
fi
schema_abs="$(cd "$(dirname "$schema")" && pwd)/$(basename "$schema")"

find_repo() {
  if [[ -n "${OPENAPI_SCHEMAS_REPO:-}" ]]; then
    echo "$OPENAPI_SCHEMAS_REPO"
    return
  fi

  local here parent
  here="$(pwd)"
  parent="$(dirname "$here")"
  for candidate in \
    "$here/../openapi-schemas" \
    "$parent/openapi-schemas" \
    "$HOME/openapi-schemas" \
    "$HOME/src/openapi-schemas" \
    "$HOME/projects/openapi-schemas"; do
    if [[ -f "$candidate/.spectral.yml" ]]; then
      (cd "$candidate" && pwd)
      return
    fi
  done
}

repo="$(find_repo || true)"
if [[ -z "$repo" || ! -f "$repo/.spectral.yml" ]]; then
  cat >&2 <<'MSG'
validate.sh: could not find the openapi-schemas repository.

Clone it and point at it explicitly:

  git clone https://github.com/vtex/openapi-schemas
  OPENAPI_SCHEMAS_REPO=/path/to/openapi-schemas validate.sh schema.json
MSG
  exit 2
fi

format="${SPECTRAL_FORMAT:-stylish}"

# Run from the repository so the ruleset resolves its functions/ directory.
cd "$repo"

if [[ -x "node_modules/.bin/spectral" ]]; then
  spectral=(node_modules/.bin/spectral)
elif command -v spectral >/dev/null 2>&1; then
  spectral=(spectral)
else
  spectral=(npx --yes "@stoplight/spectral-cli@^6")
fi

exec "${spectral[@]}" lint \
  --ruleset .spectral.yml \
  --format "$format" \
  --fail-severity error \
  "$schema_abs"
