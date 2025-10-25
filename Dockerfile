FROM python:3.12-slim

# System deps for timezone data
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago

WORKDIR /app
COPY app /app

# Python deps
RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy jinja2 python-multipart

# Create data & static (if not present)
RUN mkdir -p /data /app/static

EXPOSE 8085
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8085"]
