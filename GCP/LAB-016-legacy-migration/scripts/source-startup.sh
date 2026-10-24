#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a /var/log/lab016-startup.log | logger -t lab016-startup -s 2>/dev/console) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl docker.io openssl python3 python3-venv
systemctl enable --now docker
curl -fsSLO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
bash add-google-cloud-ops-agent-repo.sh --also-install
rm -f add-google-cloud-ops-agent-repo.sh
install -d -o root -g root -m 0755 /opt/lab016
install -d -o root -g root -m 0750 /etc/lab016
echo "lab016_startup=complete"
