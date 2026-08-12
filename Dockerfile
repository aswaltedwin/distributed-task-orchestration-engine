FROM python:3.11-slim

WORKDIR /app

# Install libpq-dev for psycopg2 if needed, though psycopg2-binary usually works without it
# RUN apt-get update && apt-get install -y libpq-dev gcc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/
ENV PYTHONUNBUFFERED=1
