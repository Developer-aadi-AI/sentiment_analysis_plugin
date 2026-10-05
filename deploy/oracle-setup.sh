#!/usr/bin/env bash
# One-time setup on an Oracle Cloud Always Free Ubuntu VM.
# Usage (on the VM):  bash oracle-setup.sh <git-repo-url> [branch]
set -euo pipefail

REPO_URL="${1:?usage: oracle-setup.sh <git-repo-url> [branch]}"
BRANCH="${2:-main}"
APP_DIR="$HOME/review-responder"

echo "==> Installing Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi
sudo systemctl enable --now docker

echo "==> Opening port 8000 in the VM firewall (Oracle Ubuntu images block it by default)"
if ! sudo iptables -C INPUT -p tcp --dport 8000 -j ACCEPT 2>/dev/null; then
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
  sudo apt-get install -y iptables-persistent >/dev/null || true
  sudo netfilter-persistent save || true
fi

echo "==> Fetching the code"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  cp deploy/env.production.example .env
  chmod 600 .env
  echo
  echo "!! Created $APP_DIR/.env from the template."
  echo "!! Fill in LLM_API_KEY and ADMIN_TOKEN (openssl rand -hex 32), then re-run this script."
  exit 0
fi

echo "==> Building and starting (restart: always)"
sudo docker compose up -d --build
sleep 5
curl -fsS http://127.0.0.1:8000/health && echo && echo "==> Up. Public URL: http://$(curl -fsS ifconfig.me):8000/health"
