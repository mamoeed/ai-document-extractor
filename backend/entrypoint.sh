#!/bin/sh
# Backend container entrypoint: check config -> migrate -> serve.
set -e
python -m app.check_config
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --proxy-headers --forwarded-allow-ips='*'
