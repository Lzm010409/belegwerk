# Ein Bild, eine Stufe. Alle Abhaengigkeiten liegen als vorgebaute Wheels vor,
# deshalb braucht der Bau keinen Compiler — und ohne Compiler lohnt der zweite
# Bauabschnitt nicht mehr (siehe ADR 0008).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    TZ=Europe/Berlin

# Systemabhaengigkeiten: WeasyPrint braucht Pango, Cairo und HarfBuzz,
# das Dokumentenpaket den zweiten Extraktionspfad aus poppler-utils.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 \
      libpangoft2-1.0-0 \
      libharfbuzz0b \
      libfribidi0 \
      libcairo2 \
      libgdk-pixbuf-2.0-0 \
      shared-mime-info \
      fonts-dejavu-core \
      poppler-utils \
      tzdata \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip setuptools wheel \
 && pip install . \
 && python -c "import belegwerk.anwendung"

COPY alembic.ini ./
COPY migrationen ./migrationen
COPY skripte ./skripte

RUN mkdir -p /data/uploads /data/ausgaben \
 && groupadd --system belegwerk \
 && useradd --system --gid belegwerk --home-dir /home/belegwerk --create-home belegwerk \
 && chown -R belegwerk:belegwerk /data /app

VOLUME ["/data"]
USER belegwerk
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/gesundheit || exit 1

CMD ["uvicorn", "belegwerk.anwendung:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
