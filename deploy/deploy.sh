#!/usr/bin/env bash
# Deploy (or redeploy) FraudStream on the server, then prove it works.
#
# Run ON THE SERVER from the project folder:
#     bash deploy/deploy.sh
#
# Steps: pre-flight checks -> pull latest code -> build + start -> wait for health -> smoke test.
# Exit code 0 = deployed and verified; anything else = look at the printed step.

set -euo pipefail
cd "$(dirname "$0")/.."            # always run from the project root, wherever it is called from

echo "== 1/5 pre-flight checks"
[ -f .env ] || { echo "FAIL: .env is missing (copy .env.example and set REAL passwords)"; exit 1; }
[ -f artifacts/fraud_model_v1.joblib ] || {
    echo "FAIL: model missing -> copy it from your laptop with scp (docs/aws-deployment.md step 6)"; exit 1; }
grep -q '^COMPOSE_FILE=' .env || {
    echo "FAIL: add this line to .env:  COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml"; exit 1; }

echo "== 2/5 latest code from GitHub"
git pull --ff-only                 # --ff-only: refuse to create a merge if the server has local edits

echo "== 3/5 build images and start all services"
docker compose up -d --build       # COMPOSE_FILE in .env adds the production overrides automatically

echo "== 4/5 wait until the api is healthy (max 3 minutes)"
for _ in $(seq 1 36); do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q api)" 2>/dev/null || echo starting)
    [ "$status" = "healthy" ] && break
    sleep 5
done
docker compose ps -a
[ "$status" = "healthy" ] || { echo "FAIL: api not healthy -> docker compose logs api migrate topics"; exit 1; }

echo "== 5/5 end-to-end smoke test (runs inside the api container, no Python needed on the server)"
docker compose exec -T api python -m scripts.smoke_test

echo
echo "DEPLOYED AND VERIFIED"