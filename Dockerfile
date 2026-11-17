# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements/ /app/requirements/
RUN pip install --upgrade pip
RUN pip install -r requirements/base.txt

# Copy the current directory contents into the container at /app
COPY . /app/

# Collect static files
RUN SECRET_KEY="dummy_secret_for_build" \
    DEBUG=True \
    DB_NAME="dummy" \
    DB_USER="dummy" \
    DB_PASSWORD="dummy" \
    python manage.py collectstatic --noinput

# Expose port 8000
EXPOSE 8000

# Run Daphne (ASGI server)
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
