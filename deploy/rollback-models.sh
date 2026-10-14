#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Restore the original application images without changing database migrations.
docker compose --env-file .env \
    -f docker-compose.yml \
    -f docker-compose.build.yml \
    -f docker-compose.demo.yml \
    up -d --no-deps --no-build --pull never ai-service admin-server
docker restart eaos-gateway
