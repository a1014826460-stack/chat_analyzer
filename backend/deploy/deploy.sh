#!/usr/bin/env sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env ]; then
  echo "Missing backend/.env. Copy deploy/server.env.example and fill server-only secrets." >&2
  exit 1
fi

docker compose pull
docker compose up --build -d
docker compose ps
