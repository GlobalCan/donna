#!/usr/bin/env bash
# harden-droplet.sh — run once on a fresh Ubuntu 24.04 droplet as root.
# Creates `bot` user, hardens SSH, installs Docker + sops + age, sets up ufw.
set -euo pipefail

BOT_USER="${BOT_USER:-bot}"
TARGET_HOME="/home/${BOT_USER}"

# Wait for any running apt/dpkg operation to finish. On a fresh DO droplet the
# cloud-init / unattended-upgrades daemon may hold the dpkg lock during the
# first few minutes after boot; racing it with our own apt calls causes the
# script to die mid-way with "Could not get lock /var/lib/dpkg/lock-frontend".
wait_for_apt_lock() {
    local waited=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
       || fuser /var/lib/dpkg/lock >/dev/null 2>&1 \
       || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
        if (( waited == 0 )); then
            echo "  waiting for another apt/dpkg process to release its lock..."
        fi
        sleep 3
        waited=$((waited + 3))
        if (( waited > 300 )); then
            echo "  still locked after 5 min — aborting" >&2
            exit 1
        fi
    done
}

echo "[1/9] creating user ${BOT_USER}"
if ! id -u "${BOT_USER}" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "${BOT_USER}"
    usermod -aG sudo "${BOT_USER}"
fi

echo "[2/9] copying SSH authorized_keys from root to ${BOT_USER}"
mkdir -p "${TARGET_HOME}/.ssh"
cp /root/.ssh/authorized_keys "${TARGET_HOME}/.ssh/authorized_keys"
chown -R "${BOT_USER}:${BOT_USER}" "${TARGET_HOME}/.ssh"
chmod 700 "${TARGET_HOME}/.ssh"
chmod 600 "${TARGET_HOME}/.ssh/authorized_keys"

echo "[3/9] hardening sshd"
cat > /etc/ssh/sshd_config.d/99-donna-hardening.conf <<EOF
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
AllowUsers ${BOT_USER}
MaxAuthTries 3
LoginGraceTime 20
EOF
systemctl reload ssh

echo "[4/9] ufw firewall"
wait_for_apt_lock
apt-get update -y
wait_for_apt_lock
DEBIAN_FRONTEND=noninteractive apt-get install -y ufw fail2ban unattended-upgrades
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw --force enable

systemctl enable --now fail2ban

# Enable the auto-update schedule via direct config instead of
# `dpkg-reconfigure`, which can launch an immediate upgrade run that holds the
# dpkg lock and blocks subsequent apt calls in this script.
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "[5/9] docker"
wait_for_apt_lock
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${BOT_USER}"

echo "[6/9] sops + age"
wait_for_apt_lock
DEBIAN_FRONTEND=noninteractive apt-get install -y age
if ! command -v sops >/dev/null 2>&1; then
    curl -fsSL -o /tmp/sops.deb \
        https://github.com/getsops/sops/releases/download/v3.9.1/sops_3.9.1_amd64.deb
    wait_for_apt_lock
    dpkg -i /tmp/sops.deb
    rm /tmp/sops.deb
fi

echo "[7/9] /etc/bot for the age key"
mkdir -p /etc/bot
chown "${BOT_USER}:${BOT_USER}" /etc/bot
chmod 700 /etc/bot
echo "  --> upload your age key via: scp ~/.scout/age.key droplet:/etc/bot/age.key"

echo "[8/9] /data mount"
mkdir -p /data/donna /data/phoenix
chown -R "${BOT_USER}:${BOT_USER}" /data

echo "[9/9] systemd timer template (deploy pipeline)"
cat > /etc/systemd/system/donna-update.service <<'EOF'
[Unit]
Description=Pull new Donna image and restart containers

[Service]
Type=oneshot
WorkingDirectory=/home/bot/donna
ExecStart=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d
User=bot
EOF

cat > /etc/systemd/system/donna-update.timer <<'EOF'
[Unit]
Description=Donna auto-update timer (every 5 min)

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=donna-update.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
echo "Done. Next:"
echo "  1. scp ~/.scout/age.key root@DROPLET:/etc/bot/age.key && chmod 600 /etc/bot/age.key && chown bot:bot /etc/bot/age.key"
echo "  2. log in as ${BOT_USER}, clone the repo into ~/donna"
echo "  3. docker login ghcr.io -u <bot-ops-github-user>"
echo "  4. systemctl enable --now donna-update.timer"
