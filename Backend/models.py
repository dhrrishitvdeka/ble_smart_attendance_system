"""SQLite models for the cloud mirror of the teacher laptop DB (spec §18-20)."""
from sqlalchemy import String, Integer, BigInteger, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Attendance(Base):
    __tablename__ = "attendance"
    attendance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    student_id: Mapped[str] = mapped_column(String(32), index=True)
    timestamp: Mapped[int] = mapped_column(BigInteger)
    verification_status: Mapped[str] = mapped_column(String(16))
    route_type: Mapped[str] = mapped_column(String(8))
    rssi_evidence: Mapped[int] = mapped_column(Integer, nullable=True)
    hop_count: Mapped[int] = mapped_column(Integer, default=0)
    via_student: Mapped[str] = mapped_column(String(128), nullable=True)
    synced: Mapped[bool] = mapped_column(Boolean, default=True)
