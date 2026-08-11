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
sudo -u postgres psql -c "CREATE USER attendance_user WITH PASSWORD '$DB_PASSWORD';" || echo "User 'attendance_user' might already exist."
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE attendance TO attendance_user;"
sudo -u postgres psql -d attendance -c "GRANT ALL ON SCHEMA public TO attendance_user;"

# Ensure Redis is running
sudo systemctl enable redis-server
sudo systemctl start redis-server

echo "======================================"
echo " Setup Complete!"
echo " PostgreSQL is running on 127.0.0.1:5432"
echo " Redis is running on 127.0.0.1:6379"
echo "======================================"
echo "Please remember your DB password for the GitHub Secrets (DB_PASSWORD)."
