# Build context: repository root (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Third-party dependencies of the package and the backend (cached until a pyproject changes).
COPY packages/po_extractor/pyproject.toml /tmp/deps/po_extractor.toml
COPY backend/pyproject.toml /tmp/deps/backend.toml
RUN python -c "import tomllib; \
projects = [tomllib.load(open(f'/tmp/deps/{n}.toml', 'rb'))['project'] for n in ('po_extractor', 'backend')]; \
print('\n'.join(d for p in projects for d in p['dependencies'] + p.get('optional-dependencies', {}).get('dev', [])))" \
    > /tmp/deps/requirements.txt \
    && pip install -r /tmp/deps/requirements.txt

# 2) The po_extractor package itself (framework-free, installed like any library).
COPY packages/po_extractor /app/packages/po_extractor
RUN pip install --no-deps /app/packages/po_extractor

# 3) Backend source, samples (for `pytest -m live` inside the container).
COPY backend /app/backend
COPY samples /app/samples

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data/uploads \
    && chown -R app:app /data/uploads /app \
    && chmod +x /app/backend/entrypoint.sh
USER app
WORKDIR /app/backend

EXPOSE 8000
CMD ["./entrypoint.sh"]
