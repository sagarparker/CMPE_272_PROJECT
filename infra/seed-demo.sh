#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
node -e 'if(Number(process.versions.node.split(".")[0])<22){console.error("Use Node.js 24 LTS (for example: nvm use 24), then rerun.");process.exit(1)}'
# New fixture uploads must generate visual descriptions as part of processing.
export ML_CAPTION_ENABLED=true
docker compose build ml-api
docker compose run --rm --no-deps ml-worker python -m mediamesh_ml.seed_enrich --check-model
docker compose up -d --build --wait --wait-timeout 180 \
  postgres keycloak azurite blob-init backend gemma-embed ml-api ml-worker frontend
docker compose --profile test build ml-tests
mkdir -p ml-service/data/demo
docker compose --profile test run --rm --no-deps \
  -v "$PWD/ml-service/data/demo:/data/demo" ml-tests \
  python -m mediamesh_ml.dataset --manifest evaluation/demo-manifest.json --directory /data/demo
npm --prefix frontend ci
(cd frontend && npx playwright install chromium && npm run seed:demo)
