#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
# Change this default for quick local tests. Allowed image counts: 20, 50, 100, 500.
DEFAULT_IMAGES=20
IMAGES=${1:-$DEFAULT_IMAGES}
if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [20|50|100|500]" >&2
  exit 2
fi
case "$IMAGES" in
  -h|--help) echo "Usage: $0 [20|50|100|500] (default: $DEFAULT_IMAGES)"; exit 0 ;;
  20|50|100|500) ;;
  *) echo "Image count must be 20, 50, 100 or 500" >&2; exit 2 ;;
esac
node -e 'if(Number(process.versions.node.split(".")[0])<22){console.error("Use Node.js 24 LTS (for example: nvm use 24), then rerun.");process.exit(1)}'
# Fail on missing configuration before building or downloading anything.
docker compose config --quiet
export ML_CAPTION_ENABLED=true
docker compose build ml-api
docker compose run --rm --no-deps ml-worker python -m mediamesh_ml.seed_enrich --check-model
docker compose up -d --build --wait --wait-timeout 180 \
  postgres keycloak azurite blob-init backend gemma-embed ml-api ml-worker frontend
mkdir -p ml-service/data/demo
node frontend/scripts/seed-demo.mjs --images "$IMAGES"
