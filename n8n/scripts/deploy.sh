#!/usr/bin/env bash
# Deploys the n8n workflows from the repo: pull, import, publish, restart, then checks n8n is up.
# GitHub Actions runs it over SSH on every push to main that changes n8n/ (.github/workflows/deploy-n8n.yml);
# it can also be run by hand on the server:  bash /opt/ntstays/n8n/scripts/deploy.sh
# It never touches .env: after editing .env, run  docker compose up -d --force-recreate n8n
set -euo pipefail

exec 9>/tmp/ntstays-deploy.lock
flock -n 9 || { echo "Another deploy is already running."; exit 1; }

cd "$(dirname "$0")/.."                      # /opt/ntstays/n8n
echo "== Pulling the latest version"
git -C .. pull --ff-only
git -C .. log --oneline -1

echo "== Applying docker-compose.yml (e.g. a new n8n version)"
docker compose up -d

# The error-alert workflow first: the others point to it.
files="ntstays-error-alert.json $(cd workflow && ls *.json | grep -v '^ntstays-error-alert\.json$' | tr '\n' ' ')"
wf_id() { docker compose exec -T n8n node -e 'console.log(require(process.argv[1]).id)' "/workflows/$1"; }

echo "== Importing workflows"
for f in $files; do docker compose exec -T n8n n8n import:workflow --input="/workflows/$f"; done
echo "== Publishing workflows"
for f in $files; do docker compose exec -T n8n n8n publish:workflow --id="$(wf_id "$f")"; done

echo "== Restarting n8n"
docker compose restart n8n
domain=$(grep -E '^N8N_DOMAIN=' .env | cut -d= -f2- | tr -d "\"'\r")
for i in $(seq 1 30); do
  if curl -fsS -o /dev/null "https://$domain/healthz"; then
    sleep 20                                 # let the new version take over from the old one
    echo "== Deployed: n8n is up at https://$domain"
    exit 0
  fi
  sleep 5
done
echo "n8n did not come back within 2.5 minutes. Check: docker compose logs --tail=100 n8n"
exit 1
