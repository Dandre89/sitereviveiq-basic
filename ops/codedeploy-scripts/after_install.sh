#!/bin/bash
set -e
cd /opt/sitereviveiq

if [ ! -f .env.production ]; then
  echo "ERROR: /opt/sitereviveiq/.env.production is missing."
  echo "This file is never part of the deploy zip (it holds secrets) — it must"
  echo "already exist on the instance from the first manual setup. See README section 3."
  exit 1
fi

docker compose -f compose.production.yaml build
