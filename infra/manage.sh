#!/bin/sh
set -eu

usage() {
  cat <<'USAGE'
Usage: ./infra/manage.sh COMMAND

  start [--with-ui|--without-ui]    Build and start the integrated stack (UI on by default)
  start SERVICE                    Build and start a service and its dependencies
  stop [SERVICE]                   Stop the stack or one service, preserving containers and data
  restart [--with-ui|--without-ui]  Stop, rebuild, and start the stack (UI on by default)
  restart SERVICE                  Stop, rebuild, and start only the named service
  status                           Show running and stopped containers
  logs [SERVICE ...]               Follow the last 100 log lines per service (Ctrl+C to exit)
  help                             Show this help

The integrated UI service is frontend. Other services include backend, ml-api,
ml-worker, gemma-embed, ollama, postgres, keycloak, azurite, blob-init, and prometheus.
USAGE
}

invalid_usage() {
  usage >&2
  exit 2
}

command_name="${1:-help}"
target_service=""
with_ui=true
if [ "$#" -gt 0 ]; then
  shift
fi

case "$command_name" in
  help|-h|--help)
    [ "$#" -eq 0 ] || invalid_usage
    usage
    exit 0
    ;;
  start|restart|stop)
    [ "$#" -le 1 ] || invalid_usage
    case "${1-}" in
      '') [ "$#" -eq 0 ] || invalid_usage ;;
      --with-ui) [ "$command_name" != stop ] || invalid_usage ;;
      --without-ui) [ "$command_name" != stop ] || invalid_usage; with_ui=false ;;
      -*) invalid_usage ;;
      *) target_service="$1" ;;
    esac
    ;;
  status) [ "$#" -eq 0 ] || invalid_usage ;;
  logs)
    for service do
      case "$service" in ''|-*) invalid_usage ;; esac
    done
    ;;
  *) printf 'Unknown command: %s\n' "$command_name" >&2; invalid_usage ;;
esac

cd "$(dirname "$0")/.."
docker info >/dev/null

compose() {
  docker compose "$@"
}

start_stack() {
  if [ "$with_ui" = false ]; then
    services="$(compose config --services)"
    set --
    while IFS= read -r service; do
      case "$service" in
        ''|frontend) ;;
        *) set -- "$@" "$service" ;;
      esac
    done <<EOF
$services
EOF
    compose stop frontend
    if [ "$#" -gt 0 ]; then
      compose up -d --build "$@"
    fi
  else
    compose up -d --build
    printf '\nMediaMesh: http://localhost:8080\n'
  fi
  printf 'Follow model setup: ./infra/manage.sh logs gemma-embed ollama-init\n'
}

case "$command_name" in
  start)
    if [ -n "$target_service" ]; then
      compose up -d --build "$target_service"
    else
      start_stack
    fi
    ;;
  stop) compose stop "$@" ;;
  restart)
    if [ -n "$target_service" ]; then
      compose stop "$target_service"
      compose up -d --build --no-deps "$target_service"
    else
      compose stop
      start_stack
    fi
    ;;
  status) compose ps --all ;;
  logs) exec docker compose logs --tail 100 --follow "$@" ;;
esac
