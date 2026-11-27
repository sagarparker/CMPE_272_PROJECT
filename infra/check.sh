#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export DOCKER_HOST="${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}"
mvn -B -f backend/pom.xml -Dapi.version=1.44 verify
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
python3 -m unittest discover -s infra/deploy -p 'test_*.py'
docker compose --profile test build ml-tests
docker compose --profile test run --rm ml-tests ruff check src tests
docker compose --profile test run --rm ml-tests
docker compose run --rm --no-deps --entrypoint promtool prometheus check config /etc/prometheus/prometheus.yml
docker compose run --rm --no-deps --entrypoint promtool prometheus test rules /etc/prometheus/search-rules.test.yml
