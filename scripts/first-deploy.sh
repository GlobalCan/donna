#!/usr/bin/env bash
# first-deploy.sh — bootstrap on the droplet after harden-droplet.sh.
# Run as the `bot` user in /home/bot.
set -euo pipefail

REPO_URL="${REPO_URL:-git@github.com:GlobalCan/donna.git}"
CLONE_DIR="${CLONE_DIR:-/home/bot/donna}"

if [[ ! -d "${CLONE_DIR}" ]]; then
    echo "cloning ${REPO_URL} -> ${CLONE_DIR}"
    git clone "${REPO_URL}" "${CLONE_DIR}"
fi
cd "${CLONE_DIR}"

if [[ ! -f .env ]]; then
    echo ".env missing — copy .env.example to .env and fill in secrets, or use sops"
    cp .env.example .env
    echo "edit ${CLONE_DIR}/.env then re-run"
    exit 1
fi

echo "logging into GHCR (needs GHCR_TOKEN env)"
if [[ -n "${GHCR_TOKEN:-}" && -n "${GHCR_USER:-}" ]]; then
    echo "${GHCR_TOKEN}" | docker login ghcr.io -u "${GHCR_USER}" --password-stdin
fi

echo "docker compose pull + up"
docker compose pull
docker compose up -d

echo "running migrations inside bot container"
docker compose exec -T bot alembic upgrade head

echo "enabling update timer"
sudo systemctl enable --now donna-update.timer
systemctl list-timers | grep donna || true
