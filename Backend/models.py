"""SQLite models for the cloud mirror of the teacher laptop DB (spec §18-20).
Implements the 7 normalized relational tables required for university attendance verification.
"""
from sqlalchemy import String, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Teacher(Base):
    __tablename__ = "teachers"
    teacher_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))


class CourseClass(Base):
    __tablename__ = "classes"
    class_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    class_name: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(128))
    teacher_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("teachers.teacher_id"), nullable=True)


class Student(Base):
    __tablename__ = "students"
    student_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    registered_device_id: Mapped[str] = mapped_column(String(64))
    device_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    class_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("classes.class_id"), nullable=True)


class Enrollment(Base):
    __tablename__ = "enrollments"
    enrollment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    student_id: Mapped[str] = mapped_column(String(32), ForeignKey("students.student_id"), index=True)
    class_id: Mapped[str] = mapped_column(String(32), ForeignKey("classes.class_id"), index=True)
    __table_args__ = (UniqueConstraint("student_id", "class_id", name="uq_student_class"),)


class ClassSession(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    class_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("classes.class_id"), nullable=True)
    teacher_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("teachers.teacher_id"), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_time: Mapped[int] = mapped_column(BigInteger)
    expiration_time: Mapped[int] = mapped_column(BigInteger)
    random_nonce: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")


class Attendance(Base):
    __tablename__ = "attendance"
    attendance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    student_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[int] = mapped_column(BigInteger)
    verification_status: Mapped[str] = mapped_column(String(16))
    route_type: Mapped[str] = mapped_column(String(8))
    rssi_evidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hop_count: Mapped[int] = mapped_column(Integer, default=0)
    via_student: Mapped[str | None] = mapped_column(String(128), nullable=True)
    synced: Mapped[bool] = mapped_column(Boolean, default=True)
    teacher_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    log_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    operator_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[str | None] = mapped_column(String(512), nullable=True)


class RelayEvent(Base):
    __tablename__ = "relay_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str] = mapped_column(String(64), index=True)
    source_student_id: Mapped[str] = mapped_column(String(32), index=True)
    relay_student_id: Mapped[str] = mapped_column(String(32), index=True)
    hop_count: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))


