FROM python:3.12.13-alpine3.24@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS base
ARG RELEASE_VERSION=dev
ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.version="${RELEASE_VERSION}" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/app/.local/bin:${PATH}"
WORKDIR /app
RUN apk add --no-cache \
        curl=8.21.0-r0 \
        libpq=18.6-r0 \
        tesseract-ocr=5.5.2-r0 \
        tesseract-ocr-data-spa=5.5.2-r0 \
    && addgroup -S app \
    && adduser -S -G app -h /home/app app \
    && mkdir -p /data/uploads /data/emails \
    && chown -R app:app /app /data/uploads /data/emails

# scikit-learn 1.9.0 has no musllinux wheel. Build it from the hash-verified
# source distribution outside the runtime stage, then copy only the installed
# Python tree into the final image.
FROM base AS build-dependencies
RUN apk add --no-cache --virtual .build-deps \
        build-base=0.5-r4 \
        linux-headers=7.0.0-r1
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

FROM base AS runtime
COPY --from=build-dependencies /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build-dependencies /usr/local/bin /usr/local/bin
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
COPY --chown=app:app entrypoint.sh ./entrypoint.sh
USER app
EXPOSE 8005
HEALTHCHECK --interval=15s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8005/ready || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
