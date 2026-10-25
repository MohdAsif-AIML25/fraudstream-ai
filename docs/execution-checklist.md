# Execution checklist: Docker → AWS → after

Tick each box as you finish it. Commands are for **PowerShell on Windows** unless marked *(server)*.
Details live in the linked docs; this file is only the order of work.

---

## Phase 1 — Run everything in Docker on your laptop

### 1.1 One-time setup
- [ ] Docker Desktop is **running** (whale icon in the tray). Check: `docker --version` and `docker compose version`
- [ ] Create `.env` and set your own passwords (`POSTGRES_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`):
  ```powershell
  Copy-Item .env.example .env
  notepad .env
  ```
- [ ] Python venv for the scripts (the containers don't need it):
  ```powershell
  python -m venv .venv
  .venv\Scripts\Activate.ps1
  pip install -r requirements-dev.txt
  ```

### 1.2 Data + model (skip if `artifacts\fraud_model_v1.joblib` already exists)
- [ ] ```powershell
  python -m scripts.generate_dataset
  python -m scripts.build_features
  python -m scripts.train_baselines
  python -m scripts.train_xgboost
  python -m scripts.select_model
  ```

### 1.3 Build and start the whole system
- [ ] ```powershell
  docker compose up -d --build
  ```
  What happens (see [docker-compose.yml](../docker-compose.yml)):
  1. `postgres`, `redis`, `kafka`, `prometheus`, `grafana` start
  2. `migrate` runs `alembic upgrade head`, `topics` creates the Kafka topics → both **exit 0**
  3. `api`, `worker`, `dashboard` start (one image from [Dockerfile](../Dockerfile), three commands)
- [ ] Check status:
  ```powershell
  docker compose ps -a
  ```
  Expected: `migrate` and `topics` = `Exited (0)`; `api`, `worker` = `healthy`; the rest `Up`.
  If something fails: `docker compose logs <service>`

### 1.4 Verify end-to-end
- [ ] `python -m scripts.smoke_test` → prints PASSED
- [ ] `python -m scripts.replay --limit 300 --rate 5` → normal traffic
- [ ] `python -m scripts.replay --skip 11367 --limit 600 --rate 20` → fraud-heavy slice, alerts appear live
- [ ] Open and check:

  | URL | Check |
  |---|---|
  | http://localhost:8000/docs | Swagger loads, `/health` returns ok |
  | http://localhost:8501 | review queue fills; review a few cases (approve / mark fraud) |
  | http://localhost:3000 | Grafana → FraudStream overview: panels have data |
  | http://localhost:9090/targets | api + worker targets **UP** |

- [ ] Optional: challenger model comparison
  ```powershell
  python -m scripts.train_xgboost --name xgboost_v2 --max-depth 6
  python -m scripts.compare_models --candidate artifacts/xgboost_v2.joblib
  ```
- [ ] Take screenshots now (Grafana + review queue) → `docs/images/grafana.png`, `docs/images/review-queue.png`
- [ ] Stop before moving to AWS (frees ports 3000/8000/8501 for the SSH tunnel):
  ```powershell
  docker compose down          # keeps data volumes; add -v only to wipe the databases
  ```

---

## Phase 2 — Deploy on AWS EC2

Full walkthrough with screenshots-level detail: [aws-deployment.md](aws-deployment.md).

- [ ] **Budget alert first**: Billing → Budgets → *Zero spend budget* (or $5/month) → your email
- [ ] Choose one region (e.g. `ap-south-1` Mumbai) and stay in it
- [ ] Launch EC2: Ubuntu 24.04, `c7i-flex.large` (account after 15 Jul 2025) or `t3.medium`, 20 GiB gp3,
      key pair `fraudstream-key.pem`, security group = **SSH from My IP only**
- [ ] Fix key permissions and connect:
  ```powershell
  icacls "$env:USERPROFILE\.ssh\fraudstream-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
  ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" ubuntu@<PUBLIC-IP>
  ```
- [ ] *(server)* Install Docker, then log out and back in:
  ```bash
  git clone https://github.com/MohdAsif-AIML25/fraudstream-ai.git
  cd fraudstream-ai
  bash deploy/ec2-setup.sh
  exit
  ```
- [ ] *(server)* `.env` with **new** strong passwords + the prod override line:
  ```bash
  cd fraudstream-ai && cp .env.example .env && nano .env
  #   add:  COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
  chmod 600 .env
  ```
- [ ] Copy the model (gitignored) from your laptop:
  ```powershell
  ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" ubuntu@<PUBLIC-IP> "mkdir -p ~/fraudstream-ai/artifacts"
  scp -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" artifacts\fraud_model_v1.joblib ubuntu@<PUBLIC-IP>:~/fraudstream-ai/artifacts/
  ```
- [ ] *(server)* Deploy: `bash deploy/deploy.sh` → must end with `SMOKE TEST PASSED` and `DEPLOYED AND VERIFIED`
- [ ] SSH tunnel from your laptop (leave the window open):
  ```powershell
  ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" -N -L 8000:127.0.0.1:8000 -L 8501:127.0.0.1:8501 -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 ubuntu@<PUBLIC-IP>
  ```
- [ ] Send traffic to the server through the tunnel: `python -m scripts.replay --limit 300 --rate 5`
- [ ] Screenshot Grafana + review queue **running on AWS**
- [ ] **Stop the instance** when done (EC2 → Instance state → Stop). Terminate when you no longer need it.
- [ ] EC2 → Global View: 0 running instances you forgot about

---

## Phase 3 — After deployment

### 3.1 Finish FraudStream as a portfolio piece
- [ ] Add the screenshots to the README (replace the `<!-- Add screenshots -->` comment)
- [ ] Record a 2–3 min demo video (replay → alerts appear → analyst reviews → Grafana precision panel)
- [ ] Pin the repo on GitHub; add topics (`fraud-detection`, `kafka`, `fastapi`, `mlops`, `xgboost`)
- [ ] Add FraudStream to the [Portfolio site](../../../../Portfolio/) and resume (2–3 bullet points with real numbers from the README Results)
- [ ] LinkedIn post: problem → architecture diagram → one hard bug you fixed → link ([Pillar_6_Content](../../../../Pillar_6_Content/))
- [ ] Update [Metrics](../../../../Metrics/) with what you actually did

### 3.2 Interview prep from this project
Be able to explain, without notes:
- [ ] Why Kafka between API and worker (decoupling, back-pressure, replay, DLQ)
- [ ] Point-in-time features and offline/online parity (why `test_feature_parity` exists)
- [ ] Threshold from analyst capacity (~2%) instead of 0.5
- [ ] Promotion gate + rollback with one env var
- [ ] What breaks at 100× traffic → MSK, RDS, ElastiCache, more workers, partitions
- [ ] The transactional outbox problem (README *Limitations*)

### 3.3 Optional improvements (pick at most one, only if it teaches something new)
- [ ] Transactional outbox poller
- [ ] Alertmanager → email/Slack
- [ ] Shadow scoring (challenger scores live traffic, results logged, not acted on)
- [ ] CI step that builds the Docker image and pushes to ECR

### 3.4 Next projects (empty folders waiting in `2.ML_Projects/`)
- [ ] [OpsPilot_AI](../../OpsPilot_AI/)
- [ ] [SupportPulse_AI](../../SupportPulse_AI/)
- [ ] [FactoryPulse ML](../../FactoryPulse%20ML/)

Reuse the FraudStream template: Dockerfile + compose + Alembic + Prometheus/Grafana + `deploy/` scripts + smoke test.
