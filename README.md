# Bio Attendance — Server

Django backend for the Bio Attendance system.

## Quick Start

```bash
cd server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env
# Edit .env with your database credentials
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_data

python manage.py runserver 0.0.0.0:8000
```

## Environment Variables

See `.env.example` for all required variables.

## Running Tests

```bash
pytest
```

## Local Docker Testing

To test the application locally using Docker (with Nginx), ensure you have PostgreSQL and Redis running locally (on your machine), or you have configured `.env.prod` to point to a local testing database. Then run:

```bash
# Disable BuildKit if you encounter random crashes during build
export DOCKER_BUILDKIT=0
docker compose up --build -d
```
Visit `http://localhost` to view the application running through Nginx.
