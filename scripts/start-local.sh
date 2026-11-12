#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
# This integration is optional; ordinary Windows/macOS/Linux setups retain the
# default Docker host gateway. Only update the address for our WSL service setup.
if [ -f /etc/systemd/system/ollama.service.d/10-docker-access.conf ]; then
    OLLAMA_HOST_ADDRESS=$(python3 scripts/ollama_wsl_private.py --address --update-env .env)
    export OLLAMA_HOST_ADDRESS
fi
docker compose up -d "$@"
# Docker Desktop can retain an empty WSL bind after a VM restart.
if [ -d data/reviews ] && ! docker compose exec -T backend test -d /data/reviews; then
    docker compose up -d --force-recreate --no-deps backend
fi
