#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
node -e 'if(Number(process.versions.node.split(".")[0])<22){console.error("Use Node.js 24 LTS (for example: nvm use 24), then rerun.");process.exit(1)}'
docker compose --profile test build ml-tests
mkdir -p ml-service/data/demo
docker compose --profile test run --rm --no-deps \
  -v "$PWD/ml-service/data/demo:/data/demo" ml-tests \
  python -m mediamesh_ml.dataset --manifest evaluation/demo-manifest.json --directory /data/demo
npm --prefix frontend ci
(cd frontend && npx playwright install chromium && npm run seed:demo)
