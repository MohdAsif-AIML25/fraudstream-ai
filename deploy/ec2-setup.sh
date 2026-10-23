#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu EC2 server for FraudStream.
#
# Run ON THE SERVER (after `ssh` into it):
#     bash deploy/ec2-setup.sh
# Then log out and log in again (so your user can run docker without sudo).
#
# Safe to run twice: every step checks whether it is already done.

set -euo pipefail   # stop on the first error, on unset variables, and on failures inside pipes

echo "== 1/4 system updates"
sudo apt-get update -y
sudo apt-get upgrade -y

echo "== 2/4 git"
sudo apt-get install -y git

echo "== 3/4 docker engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
    # Docker's official install script: adds Docker's apt repository and installs
    # docker-ce + the 'docker compose' plugin.
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"   # run docker without sudo (takes effect after re-login)
sudo systemctl enable --now docker   # start now AND after every reboot

echo "== 4/4 2 GB swap file (safety net: Kafka + Postgres + Python on a small server)"
if ! sudo swapon --show | grep -q /swapfile; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile          # only root may read it (it can contain memory contents)
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null   # keep after reboot
fi

echo
docker --version
docker compose version
free -h
echo
echo "DONE. Now run:  exit   then ssh in again, and continue with docs/aws-deployment.md step 5."