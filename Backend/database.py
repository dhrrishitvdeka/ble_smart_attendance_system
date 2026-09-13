"""DB engine: SQLite by default, Postgres/MySQL via DATABASE_URL (spec §25)."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Base, Teacher, CourseClass, Student

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

    db = SessionLocal()
    try:
        if not db.query(Teacher).first():
            t1 = Teacher(
                teacher_id="T001",
                name="Dr. Sharma",
                email="sharma@college.edu",
                password_hash="teach123"
            )
            db.add(t1)
            c1 = CourseClass(
                class_id="CSE-A",
                class_name="CSE-A",
                subject="Data Structures",
                teacher_id="T001"
            )
            db.add(c1)
            first_names = ["Aarav", "Diya", "Rohan", "Ishaan", "Meera", "Kabir"]
            last_names = ["Kumar", "Patel", "Verma", "Singh", "Iyer", "Shah"]
            for i in range(len(first_names)):
                sid = f"S00{i+1}"
                s = Student(
                    student_id=sid,
                    name=f"{first_names[i]} {last_names[i]}",
                    email=f"{sid.lower()}@student.college.edu",
                    password_hash="stud123",
                    registered_device_id=f"DEV-{sid}",
                    device_secret=f"SEC_{sid}_HASH",
                    class_id="CSE-A"
                )
                db.add(s)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

