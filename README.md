# Time Tracker (Docker for Windows quickstart)

## Overview
This repository contains a lightweight FastAPI + SQLite time tracking app with a small
HTML interface. The preferred deployment target for the first pass is Docker Desktop on
Windows (WSL2 backend). This document walks through the minimal steps needed to launch
the container, verify it is healthy, and explains where important files live.

## Repository layout

| Path | Description |
| --- | --- |
| `app/` | FastAPI application package (`main.py`, templates, static assets). |
| `data/` | Local development SQLite database (mounted into the container). |
| `docker-compose.yml` | Compose stack for the single `tracker` service. |
| `Dockerfile` | Image definition used by Compose/`docker build`. |
| `test.env` | Example snippet that writes a `.env` file when sourced (optional). |

The application listens on port **8085** and stores persistent state in `data/data.db`.

## Prerequisites

1. Docker Desktop for Windows with the WSL2 engine enabled.
2. A terminal session running inside WSL2 (e.g. Ubuntu). The paths in this README assume
   the repository is cloned into your WSL2 filesystem (e.g. `~/time-tracker2`).
3. Optional: rename `test.env` to `.env` or create a new `.env` file and set a long
   random `API_TOKEN` value for API authentication.

## Quick start (Docker)

1. **Clone the repository**
   ```bash
   git clone https://github.com/<your-org>/time-tracker2.git
   cd time-tracker2
   ```

2. **Prepare persistent data directory**
   ```bash
   mkdir -p data
   ```
   The directory is bind-mounted into the container at `/data`, ensuring the SQLite
   database survives container recreation.

3. **Configure environment (optional but recommended)**
   ```bash
   cp test.env .env        # or create .env manually
   nano .env               # edit API_TOKEN to a unique secret
   ```
   Compose automatically loads `.env` in the project root.

4. **Build and start the stack**
   ```bash
   docker compose up --build -d
   ```
   This command builds the image using the bundled `Dockerfile` and then starts the
   `tracker` service in the background.

5. **Verify the container**
   ```bash
   docker compose ps
   docker compose logs -f tracker
   ```
   - `State` should show `running`.
   - Logs should end with the Uvicorn startup banner showing it is listening on
     `0.0.0.0:8085`.

6. **Access the UI**
   Open `http://localhost:8085/` in your Windows browser. Static assets are served from
   `/static`, so no extra web server is required.

## Database configuration notes

- By default the application writes to `/data/data.db` inside the container (thanks to
  the `DB_URL` environment variable defined in `docker-compose.yml`).
- You can override the location with either `DB_URL` or `DATABASE_URL`. SQLite URLs are
  automatically created if the parent directory does not exist.
- For non-SQLite engines (e.g. PostgreSQL), supply the full SQLAlchemy connection URL
  via `DB_URL`. No extra `connect_args` are injected for non-SQLite drivers.

## Local development without Docker

If you want to run the API directly in WSL2 or another environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn[standard] sqlalchemy jinja2 python-multipart
export API_TOKEN=dev-token-123  # optional
uvicorn app.main:app --reload --port 8085
```

Keep the terminal open and visit `http://127.0.0.1:8085/` to confirm it is running.

## Updating dependencies

The Docker image installs runtime dependencies at build time. Rebuild the image whenever
`app/main.py` or other Python modules change:

```bash
docker compose build
```

For local virtual environments run `pip install -r requirements.txt` if/when a freeze
file is added in later iterations.

## Troubleshooting tips

- **Port already in use**: stop conflicting services or change the published port in
  `docker-compose.yml` (both the left and right side of `8085:8085`).
- **Permission errors writing the database**: ensure the Windows path that maps to
  `./data` is writable by your WSL2 user. Deleting the container will not delete the data
  because it resides on the host volume.
- **API 401 errors**: make sure the client supplies the token via
  `Authorization: Bearer <API_TOKEN>` header, or leave `API_TOKEN` unset to allow
  unauthenticated access during initial testing.

## Next steps

This baseline focuses on Docker parity. Future passes can add richer CI, automated tests,
advanced authentication, and improved frontend functionality once the foundation is
confirmed to be stable.

