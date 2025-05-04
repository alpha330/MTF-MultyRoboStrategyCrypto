# Base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# نصب پکیج‌های پایتون
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
RUN apt-get update && apt-get install -y wget gnupg
RUN apt-get update && apt-get install -y postgresql-client


# Copy app code
COPY ./app /usr/src/app

# Default command (can be overridden by docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]




