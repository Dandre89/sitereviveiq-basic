#!/bin/bash
set -e

if [ -f /opt/sitereviveiq/compose.production.yaml ]; then
  cd /opt/sitereviveiq
  docker compose -f compose.production.yaml down || true
fi
