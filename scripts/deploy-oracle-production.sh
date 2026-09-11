#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FORTRESS_ORACLE_APP_DIR:-/opt/fortress-dashboard}"
IMAGE_REF="${FORTRESS_IMAGE:?Set FORTRESS_IMAGE to the immutable image tag to deploy}"
COMPOSE_FILE="${FORTRESS_COMPOSE_FILE:-docker-compose.oracle-production.yml}"
HEALTH_URL="${ORACLE_PRODUCTION_BACKEND_URL:-http://127.0.0.1/api/health}"

cd "$APP_DIR"

if [ ! -f ".env.oracle.production" ]; then
  echo "Missing $APP_DIR/.env.oracle.production. Create it from .env.oracle.production.example before deploying."
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Missing $APP_DIR/$COMPOSE_FILE."
  exit 1
fi

if ! docker network inspect fortress-shared >/dev/null 2>&1; then
  echo "Missing external Docker network 'fortress-shared'. Create it once with:"
  echo "  docker network create fortress-shared"
  echo "and make sure docker-compose.oracle-staging.yml's Caddy has been redeployed onto it before this backend can be reached."
  exit 1
fi

export FORTRESS_IMAGE="$IMAGE_REF"

COMPOSE=(
  docker compose
  -p fortress-production
  --env-file .env.oracle.production
  -f "$COMPOSE_FILE"
)

if [ "${FORTRESS_SKIP_IMAGE_PULL:-0}" = "1" ]; then
  echo "Skipping image pull; using prebuilt local image $IMAGE_REF."
else
  "${COMPOSE[@]}" pull
fi
"${COMPOSE[@]}" up -d

echo "Waiting for backend health at $HEALTH_URL"
for attempt in $(seq 1 30); do
  status="$(curl -fsS -o /dev/null -w '%{http_code}' "$HEALTH_URL" || true)"
  if [ "$status" = "200" ]; then
    echo "Oracle production backend is healthy."
    "${COMPOSE[@]}" ps
    exit 0
  fi
  echo "Health attempt $attempt/30 returned ${status:-unreachable}"
  sleep 5
done

echo "Production deploy failed health verification."
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=150 fortress-backend-production
exit 1
