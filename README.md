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

# Preview imported student, staff, course, enrollment, and timetable data
python manage.py import_attendance_data --dry-run --exclude-student-code 26140186

# Execute after reviewing the preview and supplying the full academic-year dates
python manage.py import_attendance_data --execute \
	--academic-year-start YYYY-MM-DD \
	--academic-year-end YYYY-MM-DD \
	--exclude-student-code 26140186

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
_(You will now be inside the `/app` directory within the container)_

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

## Importing FCI Data

`import_attendance_data` reads the timetable and roster CSVs under `seedingFiles/`. It defaults to a no-write preview; use `--execute` only after reviewing the validation report. Execution requires the full `2026/2027` academic-year start and end dates. T1 defaults to `2026-09-20` through `2027-01-30` and the organization timezone is set to `Africa/Cairo`.

The source contains conflicting names for student code `26140186`; the command blocks execution unless that record is corrected or explicitly excluded with `--exclude-student-code 26140186`. The command does not flush or reset existing data. Reruns are idempotent for imported records.

Student credentials are `<student_code>@fci.edu` and `<student_code>#Fci!`. Staff receive a deterministic unique email and that same string as their password. These predictable seed credentials should only be used for controlled initial provisioning and should be changed before production use.
