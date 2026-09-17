"""DB engine: SQLite by default, Postgres/MySQL via DATABASE_URL (spec §25)."""
import os
import uuid as uuid_mod
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from .models import Administrator, Base, Teacher, CourseClass, Student, Enrollment
from .security import hash_password

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./attendance.db")

engine = create_engine(DATABASE_URL, future=True,
                       connect_args={"timeout": 30} if DATABASE_URL.startswith("sqlite:") else {})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        with engine.begin() as conn:
            inspector = inspect(conn)
            cols = {column["name"] for column in inspector.get_columns("attendance")}
            if "teacher_signature" not in cols:
                conn.execute(text("ALTER TABLE attendance ADD COLUMN teacher_signature VARCHAR(256)"))
            class_cols = {column["name"] for column in inspector.get_columns("classes")}
            if "class_code" not in class_cols:
                conn.execute(text("ALTER TABLE classes ADD COLUMN class_code VARCHAR(32)"))
                conn.execute(text("UPDATE classes SET class_code = class_id WHERE class_code IS NULL"))

    with SessionLocal.begin() as db:
        for model in (Administrator, Teacher, Student):
            for account in db.query(model).all():
                if "$" not in account.password_hash:
                    account.password_hash = hash_password(account.password_hash)
        if not db.get(Administrator, "A001"):
            db.add(Administrator(admin_id="A001", password_hash=hash_password("admin123")))
        if not db.get(Teacher, "T001"):
            db.add(Teacher(teacher_id="T001", name="Dr. Sharma", email="sharma@college.edu",
                           password_hash=hash_password("teach123")))
        db.flush()
        if not db.get(CourseClass, "CSE-A"):
            db.add(CourseClass(class_id="CSE-A", class_name="CSE-A", subject="Data Structures",
                               teacher_id="T001", class_code="CSE-A"))
        db.flush()
        first_names = ["Aarav", "Diya", "Rohan", "Ishaan", "Meera", "Kabir"]
        last_names = ["Kumar", "Patel", "Verma", "Singh", "Iyer", "Shah"]
        for i, (first, last) in enumerate(zip(first_names, last_names), 1):
            sid = f"S{i:03}"
            if not db.get(Student, sid):
                db.add(Student(student_id=sid, name=f"{first} {last}",
                               email=f"{sid.lower()}@student.college.edu",
                               password_hash=hash_password("stud123"), registered_device_id=f"DEV-{sid}",
                               device_secret=f"SEC_{sid}_HASH", class_id="CSE-A"))
        db.flush()
        for student in db.query(Student).all():
            if student.class_id and not db.query(Enrollment).filter_by(
                    student_id=student.student_id, class_id=student.class_id).first():
                db.add(Enrollment(enrollment_id=f"enr_{uuid_mod.uuid4().hex[:12]}",
                                  student_id=student.student_id, class_id=student.class_id))
