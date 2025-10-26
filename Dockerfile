FROM python:3.12-slim

# System deps for timezone data and health checks
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago

WORKDIR /app

COPY . /app

# Python deps
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        fastapi \
        uvicorn[standard] \
        sqlalchemy \
        jinja2 \
        python-multipart \
        prometheus-fastapi-instrumentator \
        alembic \
        gunicorn \
        psycopg[binary]

# Create data directory and add application user
RUN addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

EXPOSE 9444

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://127.0.0.1:9444/health || exit 1

CMD ["python", "-m", "gunicorn", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:9444", "app.main:app", "--workers", "2"]
