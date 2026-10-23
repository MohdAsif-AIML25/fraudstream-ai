# Deploying FraudStream on AWS EC2 (Day 8)

```text
your laptop ──ssh (port 22, your IP only)──▶ EC2 server (Ubuntu 24.04)
     │                                          └── docker compose: all 10 services
     └── ssh tunnel: localhost:3000/8000/8501 ──▶ Grafana / API / review dashboard
```

**Security model:** only SSH (port 22) is open, and only to your IP. Every service is bound to the
server's `127.0.0.1` (same as on your laptop since Day 1), so nothing is reachable from the internet.
You reach Grafana, the API and the dashboard through an **SSH tunnel**.

## 0. Cost control FIRST (5 minutes)

1. AWS console → **Billing and Cost Management** → **Budgets** → *Create budget* → template
   **Zero spend budget** (or a monthly budget of $5) → your email. You get an email before any charge.
2. Pick **one region** and stay in it (e.g. `ap-south-1`, Mumbai). Resources in other regions are easy to forget.
3. **Stop** the instance when you're not using it. A stopped instance costs only its disk.

## 1. Choose the instance size

| Your AWS account was created | Instance | RAM | Notes |
|---|---|---|---|
| on/after 15 July 2025 (free plan + credits) | `c7i-flex.large` | 4 GB | free-plan eligible, enough for all services |
| before 15 July 2025 | `t3.medium` | 4 GB | **not** free (small hourly cost) — stop it after the demo |

`t3.micro` (1 GB) is too small: Kafka, Postgres and three Python services don't fit.

## 2. Launch the instance (console)

EC2 → **Launch instance**:

| Setting | Value |
|---|---|
| Name | `fraudstream` |
| AMI | **Ubuntu Server 24.04 LTS** |
| Instance type | from step 1 |
| Key pair | *Create new* → `fraudstream-key`, type RSA, format **.pem** → save it (e.g. `C:\Users\<you>\.ssh\fraudstream-key.pem`) |
| Network → Security group | *Create* → allow **SSH** from **My IP** only. Add nothing else. |
| Storage | **20 GiB gp3** (images + Kafka + Postgres need space) |

Note the instance's **Public IPv4 address** (e.g. `13.233.10.20`).

## 3. Connect (PowerShell on your laptop)

Windows refuses keys that other users can read. Fix the key permissions once:

```powershell
icacls "$env:USERPROFILE\.ssh\fraudstream-key.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" ubuntu@<PUBLIC-IP>
```

## 4. Install Docker (on the server)

```bash
git clone https://github.com/MohdAsif-AIML25/fraudstream-ai.git
cd fraudstream-ai
bash deploy/ec2-setup.sh
exit                      # log out so the docker group applies, then ssh in again
```

## 5. Create the server's `.env` (on the server)

```bash
cd fraudstream-ai
cp .env.example .env
nano .env                 # set NEW strong passwords (not your laptop's), then add the line below
```

```ini
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
```

`chmod 600 .env` so only your user can read it.

## 6. Copy the model (PowerShell on your laptop, new window)

The model binary is gitignored, so `git clone` didn't bring it:

```powershell
ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" ubuntu@<PUBLIC-IP> "mkdir -p ~/fraudstream-ai/artifacts"
scp -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" artifacts\fraud_model_v1.joblib ubuntu@<PUBLIC-IP>:~/fraudstream-ai/artifacts/
```

It must come from the **same training run** as `artifacts_meta/fraud_model_v1.json` in Git.

## 7. Deploy (on the server)

```bash
bash deploy/deploy.sh
```

Expected end: `SMOKE TEST PASSED` and `DEPLOYED AND VERIFIED`. The first build takes several minutes.

## 8. Open the UIs through an SSH tunnel (PowerShell on your laptop)

```powershell
ssh -i "$env:USERPROFILE\.ssh\fraudstream-key.pem" -N `
    -L 8000:127.0.0.1:8000 -L 8501:127.0.0.1:8501 -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 `
    ubuntu@<PUBLIC-IP>
```

Leave that window open (`-N` = tunnel only, no shell). Stop local Docker first if the ports are busy. Then, on your laptop:

| URL | What |
|---|---|
| http://localhost:8000/docs | API (Swagger) |
| http://localhost:8501 | review dashboard |
| http://localhost:3000 | Grafana → FraudStream overview |
| http://localhost:9090/targets | Prometheus targets (both UP) |

Send traffic **to the server** through the tunnel, from your laptop:

```powershell
python -m scripts.replay --limit 300 --rate 5
python -m scripts.smoke_test
```

Take screenshots of Grafana and the review queue for the README.

## 9. Update after a code change

Push from your laptop, then on the server: `bash deploy/deploy.sh`.

## 10. Stop / delete (avoid charges)

| Goal | How |
|---|---|
| Pause (keeps everything, disk still billed) | EC2 → instance → **Instance state → Stop** |
| Delete everything | **Instance state → Terminate** (disk is deleted too) |
| Check nothing is left | EC2 → **Global View**: 0 running instances in all regions |

After *Stop → Start* the public IP changes; use the new one for `ssh`.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied (publickey)` | wrong user or key permissions | user is `ubuntu`; run the `icacls` line again |
| `ssh: connect to host ... timed out` | security group allows a different IP (your IP changed) | EC2 → Security group → edit SSH rule → *My IP* |
| `permission denied ... docker.sock` | didn't log out after setup | `exit`, ssh in again |
| build killed / very slow | out of memory | check `free -h`; swap was added by setup; use a 4 GB instance |
| `bind: address already in use` on the tunnel | local Docker still running on your laptop | `docker compose down` on the laptop |