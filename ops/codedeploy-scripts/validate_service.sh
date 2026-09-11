#!/bin/bash
set -e
cd /opt/sitereviveiq

for i in $(seq 1 10); do
  if docker compose -f compose.production.yaml exec -T web curl -sf http://localhost:8000/accounts/login/ > /dev/null; then
    echo "Service is up."
    exit 0
  fi
  echo "Waiting for web container to respond (attempt $i/10)..."
  sleep 5
done

echo "ERROR: web container never responded after deploy. Check logs with:"
echo "  docker compose -f compose.production.yaml logs web"
exit 1
