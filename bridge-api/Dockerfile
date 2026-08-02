FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/app/.local/bin:${PATH}"
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl tesseract-ocr tesseract-ocr-spa \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /home/app --create-home app \
    && mkdir -p /data/uploads \
    && chown -R app:app /app /data/uploads
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app entrypoint.sh ./entrypoint.sh
USER app
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8005/health || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
