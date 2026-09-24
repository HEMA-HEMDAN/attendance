# Bio Attendance — Server

Django backend for the Bio Attendance system.

## Quick Start
i may need to make a script to automate this 

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

To test the application locally using Docker (with Nginx), make sure you copy `.env.prod.example` to `.env.prod` and configure it to point to your local database, then run:

```bash
# Disable BuildKit if you encounter random crashes during build
export DOCKER_BUILDKIT=0
docker compose up --build -d
```
Visit `http://localhost` to view the application running through Nginx.

## Managing the Docker Container

Once your Docker containers are running (either locally or on your VPS), you may need to run Django commands like `migrate` or `createsuperuser`.

**1. Open a Bash shell inside the container:**
```bash
docker exec -it attendance_web bash
```

**2. Run your Django commands:**
*(You will now be inside the `/app` directory within the container)*
```bash
python manage.py migrate
python manage.py createsuperuser
```

**3. Exit the container:**
```bash
exit
```

Alternatively, you can run a single command without entering the shell:
```bash
docker exec -it attendance_web python manage.py createsuperuser
```

## Wiping and Re-seeding the Database (Production)

If you need to completely reset the production database and re-seed it with the initial demo data, you can run the following commands. **Warning: This will permanently delete all existing data.**

```bash
# 1. Flush the database (removes all data)
docker exec -it attendance_web python manage.py flush --no-input

# 2. Re-seed the data
docker exec -it attendance_web python manage.py seed_data
```
