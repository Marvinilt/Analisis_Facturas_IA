# Facturas IA para Cloudflare Containers (linux/amd64).
# La construye «wrangler deploy» desde deploy/cloudflare; también sirve en local:
#   docker build -t facturas-ia .
#   docker run --rm -p 8000:8000 --env-file .env facturas-ia
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FACTURAS_IA_DATA=/datos

# tzdata: el horario del procesamiento programado se evalúa en la zona horaria TZ (la pone el Worker).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY web ./web
COPY diseno ./diseno

RUN useradd --create-home --uid 10001 facturas \
    && mkdir -p /datos \
    && chown facturas:facturas /datos
USER facturas

EXPOSE 8000

# 1) Restaura el último respaldo guardado en Cloudflare (si falla, el contenedor no arranca vacío).
# 2) exec deja a uvicorn como proceso principal para que reciba SIGTERM y guarde el último respaldo al apagarse.
CMD ["sh", "-c", "python -m app.nube restaurar && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 60"]
