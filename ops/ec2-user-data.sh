#!/bin/bash
# Paste this whole file into EC2 "Advanced details" -> "User data" when
# launching the instance (Ubuntu 24.04 LTS AMI). Runs automatically on
# first boot — nothing to SSH in and type.
set -e

apt-get update
apt-get install -y docker.io docker-compose-plugin ruby-full wget curl

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

mkdir -p /opt/sitereviveiq
chown ubuntu:ubuntu /opt/sitereviveiq

# --- CodeDeploy agent (region must match where you launch the instance) ---
cd /home/ubuntu
wget https://aws-codedeploy-us-east-1.s3.us-east-1.amazonaws.com/latest/install
chmod +x ./install
./install auto
systemctl enable codedeploy-agent
systemctl start codedeploy-agent

echo "Bootstrap complete. Docker and the CodeDeploy agent are running."
