# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --gid 10001 aac && useradd --uid 10001 --gid aac --no-create-home aac \
    && mkdir -p /data /media/audio /static /models /run/aac \
    && chown -R aac:aac /data /media /static /models /run/aac

FROM base AS backend
COPY requirements-web.txt ./
RUN pip install --only-binary=:all: -r requirements-web.txt
COPY --chown=aac:aac . .
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["sh", "/app/container-entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]

FROM base AS inference
RUN apt-get update && apt-get install -y --no-install-recommends alsa-utils ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-inference.txt ./
RUN pip install --only-binary=:all: -r requirements-inference.txt
# No dotenv file, SQLite, history, or provider credentials in this image.
COPY --chown=aac:aac config ./config
COPY --chown=aac:aac aac ./aac
COPY --chown=aac:aac deploy_models.py ./
USER 10001:10001
CMD ["python", "-m", "aac.inference_server"]
