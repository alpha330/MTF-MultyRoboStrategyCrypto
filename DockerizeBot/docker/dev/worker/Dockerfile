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
RUN apt-get update && apt-get install -y wget gnupg 
RUN apt-get update && apt-get install -y postgresql-client

COPY ./worker .
