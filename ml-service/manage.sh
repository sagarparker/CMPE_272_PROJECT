#!/usr/bin/env bash
# Manage the standalone local ML stack and its test frontend. Requires Docker Compose.
set -Eeuo pipefail

SERVICE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

usage() {
  cat <<'USAGE'
Usage: ./ml-service/manage.sh COMMAND

  start             Start PostgreSQL, ML API, and worker only; stop the test frontend
  start --with-ui   Also build and start the optional local test frontend
  start SERVICE     Start one service plus its required dependencies
  stop              Stop the frontend, worker, API, and database; preserve all data
  stop SERVICE      Stop only the named service
  restart [--with-ui]  Stop the stack and start the selected mode
  restart SERVICE   Restart only the named service (and rebuild its image)
  status            Show running and stopped service containers
  logs [SERVICE]    Follow recent logs (Ctrl+C exits logs, not the services)
  help              Show this help

Core services: ml-worker, ml-api, postgres. Optional testing service: ml-dev-ui.
The script works from any directory and uses ml-service/.env if it exists.
First start may download Docker images, Python dependencies, and model weights.
It does not download samples or reindex existing media.
USAGE
}

command_name="${1:-help}"
with_ui=false
target_service=""
select_service() {
  case "$1" in
    ml-api|ml-worker|ml-dev-ui|postgres) target_service="$1" ;;
    *) printf 'Unknown service: %s\n' "$1" >&2; exit 2 ;;
  esac
}
case "$command_name" in
  help|-h|--help) usage; exit 0 ;;
  start|restart)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    if [[ $# -eq 2 ]]; then
      if [[ "$2" == --with-ui ]]; then with_ui=true; else select_service "$2"; fi
    fi
    ;;
  stop)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    [[ $# -eq 1 ]] || select_service "$2"
    ;;
  status) [[ $# -eq 1 ]] || { usage >&2; exit 2; } ;;
  logs)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    case "${2:-all}" in
      all|ml-dev-ui|ml-worker|ml-api|postgres) ;;
      *) printf 'Unknown service: %s\n' "$2" >&2; exit 2 ;;
    esac
    ;;
  *) printf 'Unknown command: %s\n' "$command_name" >&2; usage >&2; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || { printf 'Docker is required. Install Docker Desktop first.\n' >&2; exit 1; }
docker compose version >/dev/null 2>&1 || { printf 'Docker Compose is required.\n' >&2; exit 1; }
docker info >/dev/null 2>&1 || { printf 'Docker is not running. Start Docker Desktop and try again.\n' >&2; exit 1; }

# Keep Compose's .env discovery and relative bind mounts independent of the caller's directory.
cd "$SERVICE_DIR"
compose() {
  docker compose --project-directory "$SERVICE_DIR" -f "$SERVICE_DIR/compose.yaml" \
    --profile worker --profile ui "$@"
}

trap 'printf "\nOperation failed. Inspect service logs with: %s/manage.sh logs\n" "$SERVICE_DIR" >&2' ERR

show_urls() {
  local address
  if [[ "$with_ui" == true || "$command_name" == status ]]; then
    address="$(compose port ml-dev-ui 8080 2>/dev/null || true)"
    [[ -z "$address" ]] || printf 'Test frontend: http://%s\n' "$address"
  fi
  address="$(compose port ml-api 8000 2>/dev/null || true)"
  [[ -z "$address" ]] || printf 'API docs: http://%s/docs\n' "$address"
  return 0
}

prepare_runtime() {
  mkdir -p data/media
  printf 'Building application images (unchanged layers are reused)...\n'
  if [[ "$with_ui" == true || "$target_service" == ml-dev-ui ]]; then
    compose build ml-api ml-tools
  else
    compose build ml-api
  fi
  compose up -d --wait --wait-timeout 120 postgres
  # The local worker still requires these guarded SQL fixtures until production
  # backend integration. Use the runtime image, not the optional testing toolbox.
  compose run --rm --no-deps -v "$SERVICE_DIR/dev:/app/dev:ro" \
    ml-api python -m mediamesh_ml.migrate --local-fixture
  compose run --rm --no-deps -v "$SERVICE_DIR/dev:/app/dev:ro" \
    ml-api python -m mediamesh_ml.jobs init
  printf 'Loading the pinned model into its persistent cache...\n'
  compose run --rm --no-deps ml-api python -m mediamesh_ml.embeddings
}

check_api() {
  compose exec -T ml-api python -c \
    "import urllib.request; urllib.request.urlopen('http://localhost:8000/ready', timeout=10)"
}

start_stack() {
  if [[ -n "$target_service" ]]; then
    if [[ "$target_service" != postgres ]]; then prepare_runtime; fi
    compose up -d --wait --wait-timeout 120 "$target_service"
    if [[ "$target_service" == ml-api || "$target_service" == ml-dev-ui ]]; then check_api; fi
    printf '\nStarted %s and its required dependencies.\n' "$target_service"
    if [[ "$target_service" == ml-dev-ui ]]; then with_ui=true; fi
    show_urls
    return
  fi
  if [[ "$with_ui" == false ]]; then compose stop ml-dev-ui; fi
  prepare_runtime
  if [[ "$with_ui" == true ]]; then
    compose up -d --wait --wait-timeout 120 ml-api ml-worker ml-dev-ui
  else
    compose up -d --wait --wait-timeout 120 ml-api ml-worker
  fi
  check_api
  printf '\nLocal ML stack is ready.\n'
  show_urls
}

stop_stack() {
  if [[ -n "$target_service" ]]; then
    compose stop "$target_service"
    printf 'Stopped %s. Stored data is preserved.\n' "$target_service"
    return
  fi
  printf 'Stopping the frontend, worker, and API; allowing the worker to drain...\n'
  compose stop ml-dev-ui ml-worker ml-api
  # Stop the database only after the worker has finished or its grace period elapsed.
  compose stop postgres
  printf 'Stopped. Database, model cache, uploads, and embeddings are preserved.\n'
}

case "$command_name" in
  start) start_stack ;;
  stop) stop_stack ;;
  restart) stop_stack; start_stack ;;
  status) compose ps -a ml-dev-ui ml-worker ml-api postgres; show_urls ;;
  logs)
    trap - ERR  # Ctrl+C is the normal way to leave a following log stream.
    if [[ "${2:-all}" != all ]]; then
      compose logs --tail 100 --follow "$2"
    else
      compose logs --tail 100 --follow ml-worker ml-api postgres
    fi
    ;;
esac
