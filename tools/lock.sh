#!/usr/bin/env bash
# Regenerate the hashed lockfiles the CI installs from. Keeps every pinned version that still satisfies
# pyproject.toml (uv reuses the existing output file); pass --upgrade to move everything to the newest versions.
#   tools/lock.sh            # after editing dependencies in pyproject.toml
#   tools/lock.sh --check    # CI: fail if a lockfile is out of date with pyproject.toml
#   tools/lock.sh --upgrade  # deliberate dependency refresh (review the diff, run the tests)
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-}"
compile() {  # $1 = output file, rest = uv args
  local out="$1"; shift
  local target="$out"
  if [[ "$mode" == "--check" ]]; then target="$(mktemp)"; cp "$out" "$target"; fi
  local up=(); [[ "$mode" == "--upgrade" ]] && up=(--upgrade)
  uv pip compile "$@" --generate-hashes --python-version 3.12 --custom-compile-command "tools/lock.sh" \
    -o "$target" -q "${up[@]}"
  if [[ "$mode" == "--check" ]]; then
    if ! diff -q "$out" "$target" >/dev/null; then
      echo "::error::$out is out of date with pyproject.toml. Run tools/lock.sh and commit the result."
      diff -u "$out" "$target" | head -40
      exit 1
    fi
  fi
}
compile requirements/windows-py312.lock pyproject.toml --extra desktop --extra dev --python-platform windows
compile requirements/linux-test-py312.lock pyproject.toml requirements/test-extras.in --extra dev --python-platform linux
echo "lockfiles OK"
