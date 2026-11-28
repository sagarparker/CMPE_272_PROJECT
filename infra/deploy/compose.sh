#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
test -f infra/deploy/runtime/deploy.env || {
  echo "Run python3 infra/deploy/prepare.py --help first" >&2; exit 2;
}
# Secrets come from Azure Key Vault when deploy.env sets KEY_VAULT_NAME; see vault_env.py.
exec python3 infra/deploy/vault_env.py exec \
  docker compose --env-file infra/deploy/runtime/deploy.env -f compose.deploy.yaml "$@"
