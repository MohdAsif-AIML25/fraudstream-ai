# FraudStream AI – AWS Deployment Guide

**Project:** FraudStream AI – Real-Time Fraud Detection System  
**Cloud Provider:** Amazon Web Services (AWS)  
**Service:** EC2  
**Region:** Mumbai (`ap-south-1`)  
**Operating System:** Ubuntu 24.04 LTS  
**Deployment:** Docker Compose  
**Access:** SSH + SSH Local Port Forwarding  
**Status:** Deployed – Final Verification

---

## 1. AWS EC2 Configuration

| Configuration | Value |
|---|---|
| Cloud Provider | AWS |
| Service | EC2 |
| Region | `ap-south-1` (Mumbai) |
| Public IPv4 | `13.233.116.36` |
| Private IPv4 | `172.31.10.84` |
| SSH Username | `ubuntu` |
| SSH Port | `22` |
| SSH Key | `fraudstream-key.pem` |
| Project Directory | `~/fraudstream-ai` |
| Operating System | Ubuntu 24.04 LTS |
| Deployment Method | Docker Compose |

---

## 2. Deployment Architecture

```text
                  WINDOWS LAPTOP
                         |
                         |
                   SSH Connection
                     Port 22
                         |
                         v
                AWS EC2 – Ubuntu
                Public IP: 13.233.116.36
                Private IP: 172.31.10.84
                         |
                         v
                   Docker Compose
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
        FastAPI         Kafka       PostgreSQL
        Port 8000       Broker        Database
          |               |
          |               v
          |             Worker
          |               |
          +---------------+
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
         Redis        Prometheus      Grafana
                       :9090           :3000
                         |
                         v
                   Review Dashboard
                        :8501

                 SSH PORT FORWARDING
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
    localhost:8000 localhost:8501 localhost:3000

                  localhost:9090
```

---

## 3. Connect to AWS EC2

Open Windows PowerShell.

```powershell
ssh -i ".\fraudstream-key.pem" ubuntu@13.233.116.36
```

Expected terminal:

```text
ubuntu@ip-172-31-10-84:~$
```

Navigate to the project:

```bash
cd ~/fraudstream-ai
```

Verify the project:

```bash
ls -la
```

Check the latest Git commit:

```bash
git log -1 --oneline
```

Repository:

https://github.com/MohdAsif-AIML25/fraudstream-ai

---

## 4. Verify Docker Environment

Check Docker:

```bash
docker --version
```

Check Docker Compose:

```bash
docker compose version
```

Check Docker service:

```bash
sudo systemctl status docker
```

Check all containers:

```bash
docker compose ps -a
```

Check running containers:

```bash
docker compose ps
```

Check resource consumption:

```bash
docker stats --no-stream
```

List configured Compose services:

```bash
docker compose config --services
```

Verify the actual status of every configured service before marking deployment verification complete.

---

## 5. Docker Container Logs

Run these commands from `~/fraudstream-ai` on Ubuntu.

### API Logs

```bash
docker compose logs --tail=50 api
```

### Kafka Worker Logs

```bash
docker compose logs --tail=50 worker
```

### PostgreSQL Logs

```bash
docker compose logs --tail=30 postgres
```

### Redis Logs

```bash
docker compose logs --tail=30 redis
```

### Kafka Logs

```bash
docker compose logs --tail=50 kafka
```

If the service names differ, check:

```bash
docker compose config --services
```

Follow worker logs continuously:

```bash
docker compose logs -f worker
```

Press `Ctrl+C` to stop following logs without stopping the container.

---

## 6. Environment Configuration

Environment file:

```text
~/fraudstream-ai/.env
```

Verify:

```bash
ls -l .env
```

Check permissions:

```bash
stat -c "%a %n" .env
```

Set secure permissions:

```bash
chmod 600 .env
```

Production Compose configuration:

```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```

Security requirements:

- Use strong production credentials.
- Never commit `.env` to GitHub.
- Do not expose passwords in screenshots.
- Keep database credentials private.
- Review security group rules before deployment.

---

## 7. Machine Learning Model Verification

Model file:

```text
artifacts/fraud_model_v1.joblib
```

Model metadata:

```text
artifacts_meta/fraud_model_v1.json
```

Verify model:

```bash
ls -lh artifacts/fraud_model_v1.joblib
```

Verify metadata:

```bash
ls -lh artifacts_meta/fraud_model_v1.json
```

The model binary must match the training run represented by the committed metadata.

---

## 8. Application Health Verification

Check API health from Ubuntu:

```bash
curl -i http://127.0.0.1:8000/health
```

Check API documentation:

```bash
curl -I http://127.0.0.1:8000/docs
```

Check Prometheus:

```bash
curl -I http://127.0.0.1:9090/-/healthy
```

Check Grafana:

```bash
curl -I http://127.0.0.1:3000/api/health
```

Check dashboard:

```bash
curl -I http://127.0.0.1:8501
```

Use the actual health endpoints implemented by the application.

---

## 9. Deploy or Update Application

Only run this section when a new deployment or rebuild is required.

### Update from Windows

```powershell
git add .
git commit -m "Update FraudStream AI"
git push origin main
```

### Connect to EC2

```powershell
ssh -i ".\fraudstream-key.pem" ubuntu@13.233.116.36
```

### Update Repository

```bash
cd ~/fraudstream-ai
git pull origin main
```

### Deploy

```bash
bash deploy/deploy.sh
```

Expected successful messages:

```text
SMOKE TEST PASSED
DEPLOYED AND VERIFIED
```

Do not rerun deployment unnecessarily on an already working instance.

---

## 10. SSH Tunnel Configuration

The SSH tunnel provides secure local access to the AWS-hosted applications.

Open a separate Windows PowerShell window.

```powershell
ssh -i ".\fraudstream-key.pem" -N `
-L 8000:127.0.0.1:8000 `
-L 8501:127.0.0.1:8501 `
-L 3000:127.0.0.1:3000 `
-L 9090:127.0.0.1:9090 `
ubuntu@13.233.116.36
```

**Important:**

- The blank terminal is normal because `-N` does not open an interactive shell.
- Keep the PowerShell window open.
- Do not press `Ctrl+C` while using the applications.
- Open another PowerShell window for other commands.
- If the tunnel disconnects, reconnect using the same command.
- If the EC2 public IP changes after restarting, update the SSH command.

### Application URLs

| Application | Local URL |
|---|---|
| FastAPI Swagger | http://localhost:8000/docs |
| Review Dashboard | http://localhost:8501 |
| Grafana | http://localhost:3000 |
| Prometheus Targets | http://localhost:9090/targets |

---

## 11. Generate Transaction Data

Keep the SSH tunnel running.

Open another PowerShell window on the local Windows machine.

Navigate to the local project:

```powershell
cd "D:\AI_Career\Pillar_2_Portfolio_Projects\2.ML_Projects\FraudStream_AI"
```

Activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Generate transactions:

```powershell
python -m scripts.replay --limit 300 --rate 5
```

The replay script should send requests to the tunneled AWS API at `localhost:8000`.

Run the smoke test:

```powershell
python -m scripts.smoke_test
```

Expected result:

```text
SMOKE TEST PASSED
```

Verify the actual output before recording the test as successful.

---

## 12. Prometheus Monitoring

Open:

http://localhost:9090/targets

Verify configured monitoring targets.

Expected status for active targets:

```text
State: UP
```

Check:

- API metrics endpoint.
- Worker metrics endpoint.
- Other configured monitoring targets.

Only expect targets that are actually configured in Prometheus.

---

## 13. Grafana Monitoring

Open:

http://localhost:3000

Log in using the configured Grafana credentials.

Open the FraudStream overview dashboard.

Verify available metrics:

- Transactions processed.
- Fraud detection metrics.
- Transaction processing rate.
- API request metrics.
- Worker processing metrics.
- System resource utilization.
- Kafka metrics, if configured.

After replaying transactions, refresh the dashboard to verify metric updates.

---

## 14. Fraud Review Dashboard

Open:

http://localhost:8501

Verify:

- Transaction records.
- Fraud predictions.
- Risk scores.
- Review status.
- Available review actions.

Confirm that the dashboard displays actual data produced by the application.

---

## 15. Deployment Screenshots

Save screenshots in:

```text
docs/
└── screenshots/
    ├── aws-ec2-instance.png
    ├── docker-containers.png
    ├── kafka-worker-logs.png
    ├── ssh-tunnel.png
    ├── fastapi-swagger.png
    ├── review-dashboard.png
    ├── grafana-dashboard.png
    ├── prometheus-targets.png
    ├── transaction-replay.png
    └── smoke-test.png
```

### Required Screenshots

| No. | Screenshot | Purpose |
|---|---|---|
| 1 | AWS EC2 instance | Cloud infrastructure |
| 2 | Docker Compose containers | Container deployment |
| 3 | Kafka worker logs | Event processing |
| 4 | PowerShell SSH tunnel | Secure connectivity |
| 5 | FastAPI Swagger | API availability |
| 6 | Review dashboard | Fraud review interface |
| 7 | Grafana | Monitoring dashboard |
| 8 | Prometheus targets | Metrics collection |
| 9 | Transaction replay | Transaction generation |
| 10 | Smoke test | Application verification |

Do not expose passwords, private keys, or other credentials in screenshots.

---

## 16. AWS Cost Management

AWS resources may incur charges even when the application is not being used.

### Stop EC2

AWS Console → EC2 → Instances → Select the FraudStream instance.

Choose:

```text
Instance state → Stop instance
```

A stopped EC2 instance may still incur EBS storage charges.

### Start EC2 Again

Choose:

```text
Instance state → Start instance
```

Verify the new public IPv4 address.

If it changes, update the SSH connection and tunnel commands.

### Terminate EC2

When the instance is no longer required:

```text
Instance state → Terminate instance
```

Review associated EBS volumes, snapshots, Elastic IPs, and other resources separately.

Configure AWS Budget alerts to monitor spending.

---

## 17. Troubleshooting

| Problem | Possible Cause | Solution |
|---|---|---|
| SSH permission denied | Incorrect key or username | Verify key path and `ubuntu` username |
| SSH timeout | Security group or IP issue | Check SSH rule and public IP |
| Docker permission denied | User group issue | Reconnect or use `sudo` |
| Container exited | Application error | Inspect container logs |
| Container unhealthy | Health check failure | Inspect service logs |
| Port already in use | Another process is using the port | Identify the conflicting process |
| Tunnel disconnected | SSH session ended | Reconnect the tunnel |
| Localhost unavailable | Tunnel or remote service unavailable | Check tunnel and EC2 containers |
| Grafana unavailable | Grafana or tunnel issue | Inspect Grafana logs |
| Prometheus target DOWN | Scrape configuration or service issue | Inspect targets and Prometheus logs |
| Kafka worker not processing | Broker or consumer issue | Inspect Kafka and worker logs |
| Model missing | Model binary not transferred | Verify model file |
| EC2 deployment terminated | Memory or disk issue | Check `free -h`, `df -h`, and logs |

---


## 18. Final Project Summary

FraudStream AI is deployed on AWS EC2 using Docker Compose.

The deployment integrates:

- **FastAPI:** Transaction ingestion and API endpoints.
- **Machine Learning:** Fraud prediction.
- **Apache Kafka:** Real-time transaction event streaming.
- **PostgreSQL:** Persistent transaction storage.
- **Redis:** Caching and supporting operations.
- **Prometheus:** Metrics collection.
- **Grafana:** Monitoring and visualization.
- **Review Dashboard:** Fraud transaction review.
- **Docker Compose:** Container orchestration.
- **AWS EC2:** Cloud infrastructure.
- **SSH Tunneling:** Secure remote application access.

**GitHub Repository:** https://github.com/MohdAsif-AIML25/fraudstream-ai

**Deployment Platform:** AWS EC2

