from datetime import datetime

from sqlalchemy import Column, Integer, Text

from app.core.timezone import CENTRAL
from app.db.base import Base


class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client = Column(Text, nullable=False)
    client_key = Column(Text, nullable=False)
    start_iso = Column(Text, nullable=False)
    end_iso = Column(Text, nullable=True)

    minutes = Column(Integer, nullable=False, default=0)
    rounded_minutes = Column(Integer, nullable=False, default=0)
    rounded_hours = Column(Text, nullable=False, default="0.00")
    elapsed_minutes = Column(Integer, nullable=False, default=0)

    note = Column(Text, nullable=True)
    completed = Column(Integer, nullable=False, default=0)
    invoice_number = Column(Text, nullable=True)
    created_at = Column(
        Text, nullable=False, default=lambda: datetime.now(tz=CENTRAL).isoformat()
    )


__all__ = ["Entry"]
