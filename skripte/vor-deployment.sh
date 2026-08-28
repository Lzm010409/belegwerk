#!/bin/sh
# Pre-Deploy-Command fuer Coolify (Plattformdatei Abschnitt 5).
# Migrationen laufen hier, nicht beim App-Start: sonst rennen bei mehreren
# Replicas zwei Migrationen gegeneinander.
set -eu
cd /app
echo "Alembic: Migrationen einspielen"
alembic upgrade head
echo "Alembic: fertig"
