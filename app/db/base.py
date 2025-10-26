from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Ensure models are imported for Alembic's autogeneration.
import app.models.entry  # noqa: E402,F401

__all__ = ["Base"]
