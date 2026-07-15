FROM python:3.12.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home /app app

COPY requirements.txt requirements.lock ./
RUN pip install --requirement requirements.lock

COPY . .
RUN chmod +x /app/deploy/entrypoint.sh \
    && mkdir -p /app/logs /app/uploads \
    && chown -R app:app /app

USER app
EXPOSE 8000

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
