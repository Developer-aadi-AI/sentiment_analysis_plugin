#!/usr/bin/env bash
# Keeps the processed-review store between GitHub Actions runs.
#
# The SQLite store holds customer data, so it is AES-256 encrypted with the STATE_KEY secret
# and force-pushed as a single commit to the `responder-state` branch (safe in a public repo).
#
#   state.sh restore   download + decrypt into $STATE_DB   (also use locally to read drafts)
#   state.sh save      encrypt + push, only if the store changed
set -euo pipefail

BRANCH="${STATE_BRANCH:-responder-state}"
DB="${STATE_DB:-.review_responder/state.db}"
TMP="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
: "${STATE_KEY:?STATE_KEY is not set (repo secret, or export it locally)}"

crypt() { openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:STATE_KEY "$@"; }

case "${1:-}" in
  restore)
    mkdir -p "$(dirname "$DB")"
    if ! git fetch --quiet --depth=1 origin "refs/heads/$BRANCH" 2>/dev/null; then
      echo "No saved state on '$BRANCH' yet; starting fresh."
      exit 0
    fi
    git show FETCH_HEAD:state.db.enc > "$TMP/state.db.enc"
    git show FETCH_HEAD:state.sha256 > "$TMP/state.sha256.old"
    # Decrypt to a temp file first so a wrong key never leaves a corrupt store behind.
    crypt -d -in "$TMP/state.db.enc" -out "$TMP/state.db.dec"
    mv "$TMP/state.db.dec" "$DB"
    echo "Restored state from '$BRANCH'."
    ;;
  save)
    if [ ! -f "$DB" ]; then echo "No state file; nothing to save."; exit 0; fi
    new_hash="$(sha256sum "$DB" | cut -d' ' -f1)"
    if [ -f "$TMP/state.sha256.old" ] && [ "$new_hash" = "$(cat "$TMP/state.sha256.old")" ]; then
      echo "State unchanged; nothing to save."
      exit 0
    fi
    crypt -in "$DB" -out "$TMP/state.db.enc"
    blob_db="$(git hash-object -w "$TMP/state.db.enc")"
    blob_hash="$(printf '%s\n' "$new_hash" | git hash-object -w --stdin)"
    tree="$(printf '100644 blob %s\tstate.db.enc\n100644 blob %s\tstate.sha256\n' \
      "$blob_db" "$blob_hash" | git mktree)"
    commit="$(git -c user.name="review-responder[bot]" -c user.email="noreply@github.com" \
      commit-tree "$tree" -m "Update encrypted responder state")"
    for attempt in 1 2 3; do
      git push --quiet --force origin "$commit:refs/heads/$BRANCH" && break
      [ "$attempt" = 3 ] && { echo "Failed to save state" >&2; exit 1; }
      sleep 5
    done
    printf '%s\n' "$new_hash" > "$TMP/state.sha256.old"
    echo "Saved state to '$BRANCH'."
    ;;
  *)
    echo "usage: $0 restore|save" >&2
    exit 2
    ;;
esac
