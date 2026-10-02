#!/bin/sh
# The client's copy of api/openapi.yaml of zakadihq/zakadi-server, pinned by commit and
# SHA-256 (spec/02-api.md 2.11 and 2.12, D84, D133). zakadi-server publishes no package,
# so the pinned commit is the document's published form; src/zakadi/models.py is
# generated from the copy by `uv run --frozen datamodel-codegen`.
#
#   sh scripts/fetch-openapi.sh          writes openapi/openapi.yaml from the pinned
#                                        commit through gh api, refusing other bytes
#   sh scripts/fetch-openapi.sh --check  verifies the committed copy, offline
#
# A new revision of the document is a pin bump: COMMIT and SHA256 change together, then
# the copy is fetched again and models.py regenerated.
set -eu

REPO=zakadihq/zakadi-server
DOCUMENT=api/openapi.yaml
COMMIT=061fcdd7d59f1a6aa3f1b8656fdafcf311afeb6b
SHA256=5d5fe6f3529eb28a7cdc59293340f354a489a15167ab74244cf6ca4c43981b7c
COPY=openapi/openapi.yaml

usage() {
  echo "usage: sh scripts/fetch-openapi.sh [--check]" >&2
  exit 2
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | cut -d ' ' -f 1
  else
    shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}

[ "$#" -le 1 ] || usage
cd "$(dirname "$0")/.."

case "${1-}" in
  --check)
    if [ ! -f "$COPY" ]; then
      echo "fetch-openapi: $COPY is missing; sh scripts/fetch-openapi.sh writes it" >&2
      exit 1
    fi
    actual=$(sha256 "$COPY")
    if [ "$actual" != "$SHA256" ]; then
      echo "fetch-openapi: $COPY has SHA-256 $actual, not the pinned $SHA256" >&2
      exit 1
    fi
    ;;
  "")
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    gh api "repos/$REPO/contents/$DOCUMENT?ref=$COMMIT" \
      -H "Accept: application/vnd.github.raw" >"$tmp"
    actual=$(sha256 "$tmp")
    if [ "$actual" != "$SHA256" ]; then
      echo "fetch-openapi: $DOCUMENT at $COMMIT has SHA-256 $actual," >&2
      echo "not the pinned $SHA256; refused, $COPY is unchanged" >&2
      exit 1
    fi
    mkdir -p "$(dirname "$COPY")"
    cat "$tmp" >"$COPY"
    ;;
  *)
    usage
    ;;
esac
