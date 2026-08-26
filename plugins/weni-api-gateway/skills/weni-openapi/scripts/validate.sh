#!/usr/bin/env bash
#
# Lint a generated OpenAPI schema with Spectral, using the ruleset bundled in
# this skill. No checkout of openapi-schemas is required.
#
# On first run, if Node 18+ is missing from PATH, a Node LTS tarball is fetched
# into ~/.cache/weni-openapi (not the system prefix, not this repository). Then
# npm ci installs @stoplight/spectral-cli into assets/spectral/node_modules,
# which is gitignored.
#
# Usage:
#   validate.sh path/to/schema.json
#
# Environment:
#   SPECTRAL_FORMAT  spectral output format (default: stylish, use json to parse)
#
# Exit codes:
#   0  no errors (warnings may still be reported)
#   1  at least one error-severity violation
#   2  bad usage, or Node / Spectral could not be installed
set -euo pipefail

NODE_MIN_MAJOR=18
# Current Node LTS as of 2026-08. Used only when PATH has no Node >= 18.
NODE_BOOTSTRAP_VERSION="v24.19.0"

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

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
spectral_dir="$(cd "$script_dir/../assets/spectral" && pwd)"
ruleset="$spectral_dir/spectral.yml"

if [[ ! -f "$ruleset" ]]; then
  echo "validate.sh: bundled ruleset missing: $ruleset" >&2
  exit 2
fi

cache_root="${XDG_CACHE_HOME:-$HOME/.cache}/weni-openapi"
npm_cache="$cache_root/npm"

note() { echo "validate.sh: $*" >&2; }

node_major() {
  local raw
  raw="$("$1" -v 2>/dev/null || true)"
  raw="${raw#v}"
  echo "${raw%%.*}"
}

node_is_usable() {
  [[ -x "$1" ]] || return 1
  local major
  major="$(node_major "$1")"
  [[ -n "$major" && "$major" -ge "$NODE_MIN_MAJOR" ]]
}

platform_tuple() {
  local os arch
  case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux) os="linux" ;;
    *)
      echo "validate.sh: unsupported OS $(uname -s). Use macOS, Linux or WSL." >&2
      exit 2
      ;;
  esac
  case "$(uname -m)" in
    arm64|aarch64) arch="arm64" ;;
    x86_64|amd64) arch="x64" ;;
    *)
      echo "validate.sh: unsupported architecture $(uname -m)." >&2
      exit 2
      ;;
  esac
  echo "${os}-${arch}"
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    echo "validate.sh: need shasum or sha256sum to verify the Node download." >&2
    exit 2
  fi
}

download() {
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$dest" "$url"
  else
    echo "validate.sh: need curl or wget to download Node." >&2
    exit 2
  fi
}

install_bootstrap_node() {
  local plat archive prefix tmp sums expected actual url_base
  plat="$(platform_tuple)"
  archive="node-${NODE_BOOTSTRAP_VERSION}-${plat}.tar.gz"
  prefix="$cache_root/node/${NODE_BOOTSTRAP_VERSION}-${plat}"
  url_base="https://nodejs.org/dist/${NODE_BOOTSTRAP_VERSION}"

  if node_is_usable "$prefix/bin/node"; then
    echo "$prefix/bin"
    return 0
  fi

  note "PATH has no Node ${NODE_MIN_MAJOR}+. Downloading ${NODE_BOOTSTRAP_VERSION} (${plat}) into $prefix"
  mkdir -p "$prefix" "$cache_root/tmp"
  tmp="$(mktemp "${TMPDIR:-/tmp}/weni-node.XXXXXX")"
  trap 'rm -f "$tmp" "$tmp.sums"' RETURN

  download "${url_base}/${archive}" "$tmp"
  download "${url_base}/SHASUMS256.txt" "$tmp.sums"
  expected="$(awk -v f="$archive" '$2 == f { print $1 }' "$tmp.sums")"
  actual="$(sha256_of "$tmp")"
  if [[ -z "$expected" || "$expected" != "$actual" ]]; then
    rm -f "$tmp" "$tmp.sums"
    echo "validate.sh: Node tarball checksum mismatch (expected ${expected:-missing}, got $actual)." >&2
    exit 2
  fi

  rm -rf "$prefix"
  mkdir -p "$prefix"
  tar -xzf "$tmp" -C "$prefix" --strip-components=1
  rm -f "$tmp" "$tmp.sums"
  trap - RETURN

  if ! node_is_usable "$prefix/bin/node"; then
    echo "validate.sh: downloaded Node at $prefix/bin/node is not usable." >&2
    exit 2
  fi
  echo "$prefix/bin"
}

resolve_node_bin_dir() {
  local candidate
  if command -v node >/dev/null 2>&1 && node_is_usable "$(command -v node)"; then
    dirname "$(command -v node)"
    return 0
  fi
  candidate="$cache_root/node/${NODE_BOOTSTRAP_VERSION}-$(platform_tuple)/bin"
  if node_is_usable "$candidate/node"; then
    echo "$candidate"
    return 0
  fi
  install_bootstrap_node
}

ensure_spectral_cli() {
  local npm_bin
  npm_bin="$(command -v npm)"
  if [[ -z "$npm_bin" ]]; then
    echo "validate.sh: npm is missing next to Node at $NODE_BIN_DIR." >&2
    exit 2
  fi
  export npm_config_cache="$npm_cache"
  mkdir -p "$npm_cache"
  note "installing @stoplight/spectral-cli into $spectral_dir"
  if [[ -f package-lock.json ]]; then
    "$npm_bin" ci --omit=dev --no-fund --no-audit
  else
    "$npm_bin" install --omit=dev --no-fund --no-audit
  fi
}

NODE_BIN_DIR="$(resolve_node_bin_dir)"
export PATH="$NODE_BIN_DIR:$PATH"
note "node=$(command -v node) $(node -v)"

cd "$spectral_dir"

if [[ ! -x "node_modules/.bin/spectral" ]]; then
  ensure_spectral_cli
fi

if [[ ! -x "node_modules/.bin/spectral" ]]; then
  echo "validate.sh: Spectral CLI did not install (expected node_modules/.bin/spectral)." >&2
  exit 2
fi

format="${SPECTRAL_FORMAT:-stylish}"

exec node_modules/.bin/spectral lint \
  --ruleset "$ruleset" \
  --format "$format" \
  --fail-severity error \
  "$schema_abs"
