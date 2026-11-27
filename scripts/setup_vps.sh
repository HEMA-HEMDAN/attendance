#!/bin/bash
set -e

echo "======================================"
echo " Attendance VPS Initial Setup Script"
echo "======================================"

echo "Updating system packages..."
sudo apt-get update
sudo apt-get install -y ca-certificates curl

echo "Adding Docker's official GPG key..."
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "Adding Docker repository to Apt sources..."
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

echo "Installing Docker and Docker Compose..."
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

TARGET_USER="${SUDO_USER:-$USER}"
echo "Granting '$TARGET_USER' user permission to run Docker..."
sudo usermod -aG docker "$TARGET_USER"

echo "======================================"
echo " Docker Setup Complete!"
echo " IMPORTANT: You MUST log out of the VPS and log back in for the new Docker permissions to take effect!"
echo "======================================"
