"""DB engine: SQLite by default, Postgres/MySQL via DATABASE_URL (spec §25)."""
import os
import uuid as uuid_mod
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .models import Administrator, Base, Teacher, CourseClass, Student, Enrollment
from .security import hash_password

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

            cursor.execute("PRAGMA table_info(classes)")
            c_cols = [row[1] for row in cursor.fetchall()]
            if c_cols and "class_code" not in c_cols:
                cursor.execute("ALTER TABLE classes ADD COLUMN class_code VARCHAR(32)")
                cursor.execute("UPDATE classes SET class_code = class_id WHERE class_code IS NULL")
                conn.connection.commit()
    except Exception:
        pass

    db = SessionLocal()
    try:
        for model in (Administrator, Teacher, Student):
            for account in db.query(model).all():
                if "$" not in account.password_hash:
                    account.password_hash = hash_password(account.password_hash)
        if not db.get(Administrator, "A001"):
            db.add(Administrator(admin_id="A001", password_hash=hash_password("admin123")))
        if not db.query(Teacher).first():
            t1 = Teacher(
                teacher_id="T001",
                name="Dr. Sharma",
                email="sharma@college.edu",
                password_hash=hash_password("teach123")
            )
            db.add(t1)
            c1 = CourseClass(
                class_id="CSE-A",
                class_name="CSE-A",
                subject="Data Structures",
                teacher_id="T001",
                class_code="CSE-A"
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
                    password_hash=hash_password("stud123"),
                    registered_device_id=f"DEV-{sid}",
                    device_secret=f"SEC_{sid}_HASH",
                    class_id="CSE-A"
                )
                db.add(s)
                db.add(Enrollment(
                    enrollment_id=f"enr_{sid}_CSE-A",
                    student_id=sid,
                    class_id="CSE-A"
                ))
            db.commit()
        else:
            # Backfill enrollments for any existing students
            all_students = db.query(Student).all()
            for st in all_students:
                classes_to_enroll = set()
                if st.class_id:
                    classes_to_enroll.add(st.class_id)
                for cid in classes_to_enroll:
                    has_enr = db.query(Enrollment).filter_by(student_id=st.student_id, class_id=cid).first()
                    if not has_enr:
                        db.add(Enrollment(
                            enrollment_id=f"enr_{uuid_mod.uuid4().hex[:12]}",
                            student_id=st.student_id,
                            class_id=cid
                        ))
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

