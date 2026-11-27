#!/bin/sh
# Retry transient repository failures, including Maven Central's HTTP 429 responses.
set -eu
attempt=1
delay=10
log=$(mktemp)
trap 'rm -f "$log"' EXIT HUP INT TERM
while :; do
  # Force failed artifact lookups to be retried instead of using Maven's negative cache.
  if mvn -B -U "$@" >"$log" 2>&1; then
    cat "$log"
    exit 0
  else
    status=$?
  fi
  cat "$log"
  if [ "$attempt" -ge 4 ] || ! grep -Eq 'Could not transfer artifact|Connection reset|Read timed out|Temporary failure in name resolution' "$log"; then
    exit "$status"
  fi
  echo "Maven repository request failed; retrying in ${delay}s (attempt $((attempt + 1))/4)" >&2
  sleep "$delay"
  attempt=$((attempt + 1))
  delay=$((delay * 2))
done
