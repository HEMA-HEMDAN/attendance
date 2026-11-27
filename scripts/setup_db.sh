#!/bin/bash
set -e

echo "======================================"
echo " Attendance VPS Database Setup Script"
echo "======================================"

# Prompt for database password
read -s -p "Enter a secure password for the 'attendance_user' database user: " DB_PASSWORD
echo ""
read -s -p "Confirm password: " DB_PASSWORD_CONFIRM
echo ""

if [ "$DB_PASSWORD" != "$DB_PASSWORD_CONFIRM" ]; then
    echo "Error: Passwords do not match!"
    exit 1
fi

echo "Updating packages..."
sudo apt update -y

echo "Installing PostgreSQL and Redis..."
sudo apt install postgresql postgresql-contrib redis-server -y

echo "Configuring PostgreSQL Database and User..."
# Run postgres commands as the postgres user
sudo -u postgres psql -c "CREATE DATABASE attendance;" || echo "Database 'attendance' might already exist."

sudo -u postgres psql -v password="$DB_PASSWORD" -c "CREATE USER attendance_user WITH PASSWORD :'password';" || echo "User 'attendance_user' might already exist."
# password may have ' in it

sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE attendance TO attendance_user;"
sudo -u postgres psql -d attendance -c "GRANT ALL ON SCHEMA public TO attendance_user;"

# Configure PostgreSQL to accept connections from Docker containers
PG_VER=$(ls /etc/postgresql | head -n 1)
if [ -n "$PG_VER" ]; then
    echo "Configuring PostgreSQL network access..."
    sudo sed -i "s/#listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/$PG_VER/main/postgresql.conf
    sudo sed -i "s/listen_addresses = 'localhost'/listen_addresses = '*'/" /etc/postgresql/$PG_VER/main/postgresql.conf
    if ! grep -q "172.16.0.0/12" /etc/postgresql/$PG_VER/main/pg_hba.conf; then
        echo "host    all             all             172.16.0.0/12           scram-sha-256" | sudo tee -a /etc/postgresql/$PG_VER/main/pg_hba.conf
    fi
    sudo systemctl restart postgresql
fi

# Configure Redis to accept connections from localhost and Docker bridge network only
echo "Configuring Redis network access..."
DOCKER_BRIDGE_IP=$(ip -4 addr show docker0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' || echo "172.17.0.1")
sudo sed -i "s/^bind 127.0.0.1.*/bind 127.0.0.1 $DOCKER_BRIDGE_IP/" /etc/redis/redis.conf
sudo systemctl restart redis-server

echo "======================================"
echo " Setup Complete!"
echo " PostgreSQL is running and accepting container connections on 5432"
echo " Redis is running and accepting container connections on 6379"
echo "======================================"
echo "Please remember your DB password for the GitHub Secrets (DB_PASSWORD)."
