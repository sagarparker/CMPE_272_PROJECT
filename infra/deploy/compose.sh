#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
test -f infra/deploy/runtime/deploy.env || {
  echo "Run python3 infra/deploy/prepare.py --help first" >&2; exit 2;
}
exec docker compose --env-file infra/deploy/runtime/deploy.env -f compose.deploy.yaml "$@"
