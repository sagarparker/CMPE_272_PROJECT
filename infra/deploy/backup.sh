#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
umask 077
destination="backups/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p backups
mkdir "$destination"
for database in mediamesh keycloak; do
  ./infra/deploy/compose.sh exec -T postgres pg_dump -U mediamesh -Fc "$database" > "$destination/$database.dump.part"
  mv "$destination/$database.dump.part" "$destination/$database.dump"
done
echo "Database dumps written to $destination. Encrypt and copy off-host; these files contain private identity/media metadata."
