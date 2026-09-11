#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FORTRESS_ORACLE_APP_DIR:-/opt/fortress-dashboard}"
IMAGE_REF="${FORTRESS_IMAGE:?Set FORTRESS_IMAGE to the immutable image tag to deploy}"
COMPOSE_FILE="${FORTRESS_COMPOSE_FILE:-docker-compose.oracle-staging.yml}"
HEALTH_URL="${ORACLE_STAGING_BACKEND_URL:-http://127.0.0.1/api/health}"

cd "$APP_DIR"

if [ ! -f ".env.oracle.staging" ]; then
  echo "Missing $APP_DIR/.env.oracle.staging. Create it from .env.oracle.staging.example before deploying."
  exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "Missing $APP_DIR/$COMPOSE_FILE."
  exit 1
fi

export FORTRESS_IMAGE="$IMAGE_REF"

COMPOSE=(
  docker compose
  --env-file .env.oracle.staging
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
    echo "Oracle staging backend is healthy."
    "${COMPOSE[@]}" ps
    exit 0
  fi
  echo "Health attempt $attempt/30 returned ${status:-unreachable}"
  sleep 5
done

echo "Staging deploy failed health verification."
"${COMPOSE[@]}" ps
"${COMPOSE[@]}" logs --tail=150 fortress-backend
exit 1
