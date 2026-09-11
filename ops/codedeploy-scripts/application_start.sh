#!/bin/bash
set -e
cd /opt/sitereviveiq

docker compose -f compose.production.yaml up -d
docker compose -f compose.production.yaml exec -T web python manage.py migrate --noinput
docker compose -f compose.production.yaml exec -T web python manage.py collectstatic --noinput
