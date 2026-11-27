#!/bin/sh
set -eu
if [ "$#" -eq 0 ]; then
  set -- start
fi
exec "$(dirname "$0")/manage.sh" "$@"
