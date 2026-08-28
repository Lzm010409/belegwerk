# syntax=docker/dockerfile:1
# Stufe 1: Abhaengigkeiten als Wheels bauen.
FROM python:3.12-slim-bookworm AS bau

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /bau
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install . \
 && /opt/venv/bin/python -c "import belegwerk.anwendung"

# Stufe 2: schlanke Laufzeit mit den Systemabhaengigkeiten fuer WeasyPrint und poppler.
FROM python:3.12-slim-bookworm AS laufzeit

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Europe/Berlin

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfribidi0 \
      libgdk-pixbuf-2.0-0 libcairo2 libffi8 shared-mime-info \
      fonts-dejavu-core poppler-utils tzdata curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system belegwerk && useradd --system --gid belegwerk --create-home belegwerk

COPY --from=bau /opt/venv /opt/venv

WORKDIR /app
# Die Anwendung selbst steckt im venv aus Stufe 1. Hierher kommt nur, was zur
# Laufzeit als Datei gebraucht wird: die Migrationen und das Pre-Deploy-Skript.
COPY alembic.ini ./
COPY migrationen ./migrationen
COPY skripte ./skripte

RUN mkdir -p /data/uploads /data/ausgaben && chown -R belegwerk:belegwerk /data /app
VOLUME ["/data"]

USER belegwerk
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/gesundheit || exit 1

CMD ["uvicorn", "belegwerk.anwendung:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
