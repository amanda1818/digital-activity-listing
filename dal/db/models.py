"""ORM models. One class per PRD §5 table. UUIDs stored as hex strings so the
same models work on SQLite (local) and PostgreSQL (production) unchanged.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Integer, Float, Boolean, DateTime, Date, ForeignKey, Text, JSON, Numeric,
)
from sqlalchemy.orm import mapped_column, Mapped, relationship
from db.database import Base


def _id() -> str:
    return uuid.uuid4().hex


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Study(Base):
    __tablename__ = "studies"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String)
    start_date: Mapped[datetime] = mapped_column(Date)
    end_date: Mapped[datetime] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft|consent|active|analysis|closed|deleted
    data_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    roles: Mapped[list["Role"]] = relationship(backref="study")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    name: Mapped[str] = mapped_column(String)
    role_family: Mapped[str] = mapped_column(String)
    current_headcount: Mapped[int] = mapped_column(Integer, default=1)
    available_minutes_per_day: Mapped[int] = mapped_column(Integer, default=420)
    cyclical: Mapped[bool] = mapped_column(Boolean, default=False)  # PRD v1.1


class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    pseudonym: Mapped[str] = mapped_column(String)  # NEVER a real name
    consent_status: Mapped[str] = mapped_column(String, default="given")  # pending|given|withdrawn
    esm_optin: Mapped[bool] = mapped_column(Boolean, default=True)


class ActivityCatalog(Base):
    __tablename__ = "activity_catalog"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    role_family: Mapped[str] = mapped_column(String)
    activity_name: Mapped[str] = mapped_column(String)
    default_classification: Mapped[str] = mapped_column(String)  # VA|NVA_necessary|NVA_waste
    keywords: Mapped[list] = mapped_column(JSON, default=list)  # app/window keywords
    is_rework_category: Mapped[bool] = mapped_column(Boolean, default=False)


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    source: Mapped[str] = mapped_column(String)  # agent|graph|gworkspace
    start_ts: Mapped[datetime] = mapped_column(DateTime)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    app_name: Mapped[str] = mapped_column(String, default="")
    window_title_hash: Mapped[str] = mapped_column(String, default="")  # hashed/category, never raw content
    category: Mapped[str] = mapped_column(String, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    signal_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    needs_attribution: Mapped[bool] = mapped_column(Boolean, default=False)  # idle gap awaiting one-tap attribution


class EsmResponse(Base):
    __tablename__ = "esm_responses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    prompt_ts: Mapped[datetime] = mapped_column(DateTime)
    response_ts: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_catalog.id"), nullable=True)
    is_rework: Mapped[bool] = mapped_column(Boolean, default=False)
    is_waiting: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new_request: Mapped[bool] = mapped_column(Boolean, default=False)
    free_note: Mapped[str] = mapped_column(Text, default="")


class EsmCorrection(Base):
    """Log of timeline corrections (PRD §B3.2 / §G4) for bias analysis."""
    __tablename__ = "esm_corrections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    old_classification: Mapped[str] = mapped_column(String)
    new_classification: Mapped[str] = mapped_column(String)


class ClassifiedBlock(Base):
    __tablename__ = "classified_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_catalog.id"), nullable=True)
    start_ts: Mapped[datetime] = mapped_column(DateTime)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    minutes: Mapped[float] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String)  # VA|NVA_necessary|NVA_waste
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    divergence_flag: Mapped[str] = mapped_column(String, default="")
    consultant_override: Mapped[str] = mapped_column(String, nullable=True)


class Volume(Base):
    __tablename__ = "volumes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_catalog.id"))
    period: Mapped[datetime] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer)


class StandardTime(Base):
    __tablename__ = "standard_times"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    activity_id: Mapped[str] = mapped_column(ForeignKey("activity_catalog.id"))
    std_minutes_per_unit: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String, default="percentile")  # percentile|engineered|waste_stripped
    set_by: Mapped[str] = mapped_column(String, default="system")


class ManloadResult(Base):
    __tablename__ = "manload_results"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"))
    period_label: Mapped[str] = mapped_column(String, default="overall")  # overall|baseline|peak
    required_headcount: Mapped[float] = mapped_column(Float)
    actual_headcount: Mapped[int] = mapped_column(Integer)
    gap: Mapped[float] = mapped_column(Float)
    va_pct: Mapped[float] = mapped_column(Float, default=0.0)
    nva_nec_pct: Mapped[float] = mapped_column(Float, default=0.0)
    nva_waste_pct: Mapped[float] = mapped_column(Float, default=0.0)


# ---------------- auth, audit, privacy (PRD §F3, §F4, §8) ----------------

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    salt: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)  # sysadmin|consultant|client_admin|participant
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    token: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user_id: Mapped[str] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="")
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String, default="")


class NameMap(Base):
    """Client-held mapping of pseudonym -> real name, ENCRYPTED at rest (PRD §8 P4)."""
    __tablename__ = "name_map"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    study_id: Mapped[str] = mapped_column(ForeignKey("studies.id"))
    participant_id: Mapped[str] = mapped_column(ForeignKey("participants.id"))
    encrypted_name: Mapped[str] = mapped_column(Text)
