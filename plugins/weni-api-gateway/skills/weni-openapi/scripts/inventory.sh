#!/usr/bin/env bash
#
# Build the API Gateway route inventory for a service repository.
#
# This wraps `manage.py api_gateway_inventory` so the developer never has to run
# it themselves: the skill calls this script, and everything the command needs
# to boot Django is discovered here instead of being asked for.
#
# What it resolves on its own:
#   - the repository (by path or by name, searched next to the workspace)
#   - the interpreter (repo virtualenv, Poetry env, or python3)
#   - GDAL / GEOS paths on macOS, which PostGIS projects need to import at all
#   - a local weni-commons checkout, when the installed release predates the
#     api_gateway_inventory command
#
# Usage:
#   inventory.sh [--repo PATH_OR_NAME] [--out PATH] [--url-prefix PREFIX]
#                [--service NAME] [--weni-commons PATH] [--python PATH]
#
# On success the absolute path of the inventory is printed to stdout, and the
# command's own summary (routes and warnings) goes to stderr.
#
# Exit codes:
#   0  inventory written
#   1  the command ran and failed
#   2  the repository, interpreter or command could not be resolved
set -uo pipefail

repo_arg=""
out_arg=".openapi/inventory.json"
url_prefix_arg=""
service_arg=""
commons_arg="${WENI_COMMONS_REPO:-}"
python_arg="${PYTHON:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo_arg="${2:-}"; shift 2 ;;
    --out) out_arg="${2:-}"; shift 2 ;;
    --url-prefix) url_prefix_arg="${2:-}"; shift 2 ;;
    --service) service_arg="${2:-}"; shift 2 ;;
    --weni-commons) commons_arg="${2:-}"; shift 2 ;;
    --python) python_arg="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)
      # Bare argument is the repository, so `inventory.sh flows` works.
      if [[ -z "$repo_arg" ]]; then repo_arg="$1"; shift; else
        echo "inventory.sh: unexpected argument: $1" >&2; exit 2
      fi
      ;;
  esac
done

note() { echo "inventory.sh: $*" >&2; }

# ---------------------------------------------------------------- repository

resolve_repo() {
  local candidate="$1"

  if [[ -z "$candidate" ]]; then
    echo "$(pwd)"
    return 0
  fi

  if [[ -d "$candidate" ]]; then
    (cd "$candidate" && pwd)
    return 0
  fi

  # A bare name like "flows": look where sibling checkouts usually live.
  local parent
  parent="$(dirname "$(pwd)")"
  local base
  for base in "$parent" "$HOME" "$HOME/src" "$HOME/projects" "$HOME/code"; do
    if [[ -d "$base/$candidate" ]]; then
      (cd "$base/$candidate" && pwd)
      return 0
    fi
  done

  return 1
}

repo="$(resolve_repo "$repo_arg")" || {
  echo "inventory.sh: could not find a repository named '$repo_arg'." >&2
  echo "Pass a path instead: inventory.sh --repo /path/to/service" >&2
  exit 2
}

if [[ ! -f "$repo/manage.py" ]]; then
  echo "inventory.sh: no manage.py in $repo — this is not a Django project." >&2
  exit 2
fi

cd "$repo"

# --------------------------------------------------------------- interpreter

resolve_python() {
  if [[ -n "$python_arg" ]]; then
    echo "$python_arg"
    return 0
  fi

  local candidate
  for candidate in ".venv/bin/python" "venv/bin/python" "env/bin/python"; do
    if [[ -x "$candidate" ]]; then
      echo "$repo/$candidate"
      return 0
    fi
  done

  if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
    echo "$VIRTUAL_ENV/bin/python"
    return 0
  fi

  if command -v poetry >/dev/null 2>&1; then
    local poetry_env
    poetry_env="$(poetry env info -p 2>/dev/null || true)"
    if [[ -n "$poetry_env" && -x "$poetry_env/bin/python" ]]; then
      echo "$poetry_env/bin/python"
      return 0
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  return 1
}

python_bin="$(resolve_python)" || {
  echo "inventory.sh: no Python interpreter found for $repo." >&2
  echo "Pass one explicitly: inventory.sh --python /path/to/python" >&2
  exit 2
}

# ------------------------------------------------------- native geo libraries

# PostGIS projects (flows) fail to import Django at all without these on macOS,
# which is friction that has nothing to do with documentation.
if [[ "$(uname -s)" == "Darwin" ]]; then
  for prefix in /opt/homebrew /usr/local; do
    if [[ -z "${GDAL_LIBRARY_PATH:-}" && -f "$prefix/lib/libgdal.dylib" ]]; then
      export GDAL_LIBRARY_PATH="$prefix/lib/libgdal.dylib"
    fi
    if [[ -z "${GEOS_LIBRARY_PATH:-}" && -f "$prefix/lib/libgeos_c.dylib" ]]; then
      export GEOS_LIBRARY_PATH="$prefix/lib/libgeos_c.dylib"
    fi
  done
fi

# ------------------------------------------------- local weni-commons fallback

COMMAND_FILE="weni_commons/management/commands/api_gateway_inventory.py"

resolve_commons() {
  local candidate
  for candidate in \
    "$commons_arg" \
    "$(dirname "$repo")/weni-commons" \
    "$HOME/weni-commons" \
    "$HOME/src/weni-commons" \
    "$HOME/projects/weni-commons"; do
    if [[ -n "$candidate" && -f "$candidate/$COMMAND_FILE" ]]; then
      (cd "$candidate" && pwd)
      return 0
    fi
  done
  return 1
}

# ------------------------------------------------------------------- run it

args=(manage.py api_gateway_inventory --out "$out_arg")
[[ -n "$url_prefix_arg" ]] && args+=(--url-prefix "$url_prefix_arg")
[[ -n "$service_arg" ]] && args+=(--service "$service_arg")

# Explicit path with trailing X's: `mktemp -t prefix` is BSD-only and GNU
# rejects it for having too few X's, which would break every Linux developer.
log="$(mktemp "${TMPDIR:-/tmp}/weni-inventory.XXXXXX")" || exit 2
trap 'rm -f "$log"' EXIT

run() {
  "$python_bin" "${args[@]}" >/dev/null 2>"$log"
  return $?
}

note "repo=$repo"
note "python=$python_bin"

status=0
run || status=$?

# Django prints this when the installed weni-commons has no such command.
if grep -q "Unknown command" "$log" 2>/dev/null; then
  commons="$(resolve_commons || true)"
  if [[ -z "$commons" ]]; then
    cat >&2 <<MSG

inventory.sh: the installed weni-commons has no api_gateway_inventory command.

Either upgrade weni-commons in this repository, or point at a local checkout
that already has it:

  inventory.sh --weni-commons /path/to/weni-commons
MSG
    exit 2
  fi

  note "installed weni-commons predates the command — using $commons via PYTHONPATH"
  export PYTHONPATH="$commons${PYTHONPATH:+:$PYTHONPATH}"
  status=0
  run || status=$?
fi

cat "$log" >&2

if [[ $status -ne 0 ]]; then
  exit "$status"
fi

# stdout carries only the artifact path, so the caller can consume it directly.
if [[ "$out_arg" = /* ]]; then
  echo "$out_arg"
else
  echo "$repo/$out_arg"
fi
