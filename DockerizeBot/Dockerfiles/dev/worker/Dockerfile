FROM python:3.11-slim

LABEL maintainer="alimahmoodi22@gmail.com"

ENV PYTHONUNBUFFERED=1

# نصب ابزارهای مورد نیاز، تنظیم منطقه زمانی و محلی
RUN apt-get update && apt-get install -y \
    iputils-ping \
    nano \
    telnet \
    graphviz \
    libgraphviz-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/worker

COPY ./requirements.txt .
COPY ./envs/dev/.env .

# نصب پکیج‌های پایتون
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
RUN apt-get update && apt-get install -y wget gnupg && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - && \
    echo "deb http://apt.postgresql.org/pub/repos/apt bullseye-pgdg main" > /etc/apt/sources.list.d/pgdg.list
RUN apt-get update && apt-get install -y postgresql-client-15

COPY ./worker .
