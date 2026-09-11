"""DB engine: SQLite by default, Postgres/MySQL via DATABASE_URL (spec §25)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./attendance.db")

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            cursor.execute("PRAGMA table_info(attendance)")
            cols = [row[1] for row in cursor.fetchall()]
            if cols and "teacher_signature" not in cols:
                cursor.execute("ALTER TABLE attendance ADD COLUMN teacher_signature VARCHAR(256)")
                conn.connection.commit()
    except Exception:
        pass
