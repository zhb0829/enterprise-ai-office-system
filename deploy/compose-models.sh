#!/bin/sh
set -eu
cd "$(dirname "$0")"
test -f .env.models
test -f docker-compose.models.json
if [ "$#" -eq 0 ]; then
    set -- ps
fi
exec docker compose \
    --env-file .env --env-file .env.models \
    -f docker-compose.yml \
    -f docker-compose.build.yml \
    -f docker-compose.demo.yml \
    -f docker-compose.models.json "$@"
