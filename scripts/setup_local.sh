#!/usr/bin/env bash
#
# Local development setup for the Bio Attendance server.
# Automates the manual "Quick Start" steps from README.md:
# virtualenv -> dev requirements -> .env -> migrations -> superuser.
#
# Usage:
#   bash scripts/setup_local.sh                  # full setup
#   bash scripts/setup_local.sh --skip-superuser # skip the admin account prompt

set -euo pipefail

# Always run from the repository root (the parent of this script's directory).
cd "$(dirname "$0")/.."

echo "=== Bio Attendance: local development setup ==="

# 1. Python check (Django 5.2 requires Python 3.10+).
if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 was not found. Install Python 3.10 or newer and re-run." >&2
  exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=${PY_VERSION%%.*}
PY_MINOR=${PY_VERSION##*.}
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "Error: Python 3.10+ is required (Django 5.2), found $PY_VERSION." >&2
  exit 1
fi
echo "Using Python $PY_VERSION"

# 2. Virtual environment
if [ ! -d venv ]; then
  echo "Creating virtual environment (venv/)..."
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3. Dependencies
echo "Installing development requirements..."
pip install --upgrade pip
pip install -r requirements/dev.txt

# 4. Environment file
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example - edit it with your database credentials before running the server."
else
  echo ".env already exists, leaving it untouched."
fi

# 5. Database migrations
echo "Applying database migrations..."
python manage.py makemigrations
python manage.py migrate

# 6. Superuser
if [ "${1:-}" != "--skip-superuser" ]; then
  echo "Create an admin account (press Ctrl+C to skip):"
  python manage.py createsuperuser || true
fi

echo "=== Setup complete ==="
echo "Start the server with: source venv/bin/activate && python manage.py runserver 0.0.0.0:8000"
