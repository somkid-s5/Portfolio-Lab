#!/usr/bin/env bash
set -Eeuo pipefail
exec > >(tee -a /var/log/lab016-startup.log | logger -t lab016-startup -s 2>/dev/console) 2>&1
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y apt-transport-https ca-certificates curl docker.io gnupg openssl python3 python3-venv
install -d -m 0755 /usr/share/keyrings
curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor --yes -o /usr/share/keyrings/cloud.google.gpg
chmod 0644 /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" >/etc/apt/sources.list.d/google-cloud-sdk.list
apt-get update
apt-get install -y google-cloud-cli
systemctl enable --now docker
curl -fsSLO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
bash add-google-cloud-ops-agent-repo.sh --also-install
rm -f add-google-cloud-ops-agent-repo.sh
curl -fsSL -o /usr/local/bin/cloud-sql-proxy https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.26.3/cloud-sql-proxy.linux.amd64
chmod 0755 /usr/local/bin/cloud-sql-proxy
install -d -o root -g root -m 0755 /opt/lab016
install -d -o root -g root -m 0750 /etc/lab016
echo "lab016_startup=complete"
