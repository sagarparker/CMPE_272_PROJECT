#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
docker info >/dev/null
docker compose up -d --build
printf '\nMediaMesh: http://localhost:8080\nFirst start downloads the CLIP model. Follow progress: docker compose logs -f ml-api ml-worker\n'
