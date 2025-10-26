from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings


BASE_DIR = Path(__file__).resolve().parent.parent.parent
_settings = get_settings()


def _normalise_database_url(raw_url: str) -> str:
    url = make_url(raw_url)
    drivername = url.drivername
    if drivername.startswith("sqlite+"):
        url = url.set(drivername="sqlite")
    elif "+" in drivername and drivername.startswith("postgresql+"):
        url = url.set(drivername="postgresql")
    return str(url)


def _sqlite_connect_args(url: str) -> Dict[str, Any]:
    if not url.startswith("sqlite"):
        return {}
    connect_args: Dict[str, Any] = {"check_same_thread": False}
    try:
        url_obj = make_url(url)
        db_path = url_obj.database
        if db_path and db_path != ":memory:":
            path = Path(db_path)
            if not path.is_absolute():
                path = (BASE_DIR / db_path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return connect_args


SYNC_DATABASE_URL = _normalise_database_url(_settings.db_url)
_connect_args = _sqlite_connect_args(SYNC_DATABASE_URL)
engine: Engine = create_engine(SYNC_DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

__all__ = ["engine", "SessionLocal"]
