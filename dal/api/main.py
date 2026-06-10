"""FastAPI service — full app (auth, consent, ingestion, ESM, idle-gaps, manload,
ML, retention, audit). Run:  uvicorn api.main:app --reload  → http://127.0.0.1:8000/docs
Participant ESM app:  http://127.0.0.1:8000/esm-app?token=<participant token>
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datetime import date as date_type
from db.database import get_session, create_all
from db.models import (
    ActivityEvent, EsmResponse, EsmCorrection, StandardTime, Participant,
    ClassifiedBlock, Study, Role, ActivityCatalog, User, AuditLog,
    Organization, Volume,
)
from auth import security as sec
from engine.classify import classify_study
from engine.manload import compute_manload
from engine import idle_gaps, ml_classify, validity
from esm_app.page import PAGE
import scheduler

app = FastAPI(title="Digital Activity Listing API", version="2.0")


@app.on_event("startup")
def _startup():
    create_all()
    scheduler.start_scheduler()


# ---------------- schemas ----------------
class LoginIn(BaseModel):
    email: str
    password: str

class ConsentIn(BaseModel):
    given: bool

class EsmIn(BaseModel):
    activity_id: Optional[str] = None
    is_rework: bool = False
    is_waiting: bool = False
    is_new_request: bool = False
    free_note: str = ""

class AttributeIn(BaseModel):
    event_id: int
    choice: str

class EventIn(BaseModel):
    participant_id: str
    source: str = "agent"
    start_ts: datetime
    end_ts: datetime
    app_name: str = ""
    window_title_hash: str = ""
    category: str = ""
    is_active: bool = True
    signal_flags: dict = {}

class StudyIn(BaseModel):
    org_id: str
    name: str
    start_date: str
    end_date: str
    retention_days: int = 30

class RoleIn(BaseModel):
    study_id: str
    name: str
    role_family: str
    current_headcount: int = 1
    available_minutes_per_day: int = 420
    cyclical: bool = False

class OrgIn(BaseModel):
    name: str

class CorrectionIn(BaseModel):
    block_id: int
    new_classification: str  # VA|NVA_necessary|NVA_waste
    new_activity_id: Optional[str] = None

class VolumeIn(BaseModel):
    study_id: str
    activity_id: str
    period: str  # YYYY-MM-DD
    count: int

class StandardTimeIn(BaseModel):
    activity_id: str
    std_minutes_per_unit: float
    method: str = "engineered"


# ---------------- auth ----------------
@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_session)):
    tok = sec.authenticate(db, body.email, body.password)
    if not tok:
        raise HTTPException(401, "bad credentials")
    user = db.query(User).filter_by(email=body.email).first()
    sec.audit(db, user, "login")
    db.commit()
    return {"token": tok, "role": user.role}


# ---------------- participant (ESM app) ----------------
@app.get("/me")
def me(user: User = Depends(sec.current_user), db: Session = Depends(get_session)):
    p = db.get(Participant, user.participant_id) if user.participant_id else None
    return {"role": user.role, "pseudonym": p.pseudonym if p else user.email,
            "consent_status": p.consent_status if p else "n/a"}

@app.post("/consent")
def consent(body: ConsentIn, user: User = Depends(sec.require_role("participant")),
            db: Session = Depends(get_session)):
    p = db.get(Participant, user.participant_id)
    p.consent_status = "given" if body.given else "withdrawn"
    sec.audit(db, user, "consent", p.consent_status)
    # PRD §F6: withdrawal immediately purges that participant's raw data
    if not body.given:
        db.query(ActivityEvent).filter_by(participant_id=p.id).delete()
        db.query(EsmResponse).filter_by(participant_id=p.id).delete()
        db.query(ClassifiedBlock).filter_by(participant_id=p.id).delete()
        sec.audit(db, user, "withdrawal_purge", p.id)
    db.commit()
    return {"consent_status": p.consent_status}

@app.get("/esm/candidates")
def esm_candidates(user: User = Depends(sec.require_role("participant")),
                   db: Session = Depends(get_session)):
    p = db.get(Participant, user.participant_id)
    role = db.get(Role, p.role_id)
    acts = db.query(ActivityCatalog).filter_by(role_family=role.role_family).all()
    return [{"id": a.id, "name": a.activity_name} for a in acts]

@app.post("/esm")
def post_esm(r: EsmIn, user: User = Depends(sec.require_role("participant")),
             db: Session = Depends(get_session)):
    db.add(EsmResponse(participant_id=user.participant_id, prompt_ts=datetime.utcnow(),
                       response_ts=datetime.utcnow(), **r.model_dump()))
    db.commit()
    return {"ok": True}

@app.get("/esm/pending-gaps")
def pending_gaps(user: User = Depends(sec.require_role("participant")),
                 db: Session = Depends(get_session)):
    return idle_gaps.pending_for_participant(db, user.participant_id)

@app.post("/esm/attribute")
def attribute(body: AttributeIn, user: User = Depends(sec.require_role("participant")),
              db: Session = Depends(get_session)):
    ev = db.get(ActivityEvent, body.event_id)
    if not ev or ev.participant_id != user.participant_id:
        raise HTTPException(404, "gap not found")
    idle_gaps.attribute_gap(db, body.event_id, body.choice)
    return {"ok": True}

@app.post("/esm/correction")
def post_correction(body: CorrectionIn,
                    user: User = Depends(sec.require_role("participant")),
                    db: Session = Depends(get_session)):
    """Log a timeline correction (PRD §B3.2, §G4). Stores before/after for bias analysis."""
    blk = db.get(ClassifiedBlock, body.block_id)
    if not blk or blk.participant_id != user.participant_id:
        raise HTTPException(404, "block not found")
    db.add(EsmCorrection(
        participant_id=user.participant_id,
        old_classification=blk.classification,
        new_classification=body.new_classification,
    ))
    blk.consultant_override = body.new_classification
    if body.new_activity_id:
        blk.activity_id = body.new_activity_id
    sec.audit(db, user, "esm_correction", str(body.block_id))
    db.commit()
    return {"ok": True}

@app.get("/esm-app", response_class=HTMLResponse)
def esm_app():
    return PAGE


# ---------------- ingestion (agent / connectors) ----------------
@app.post("/events")
def post_events(events: list[EventIn], db: Session = Depends(get_session)):
    for e in events:
        db.add(ActivityEvent(**e.model_dump()))
    db.commit()
    return {"ingested": len(events)}


# ---------------- consultant: pipeline + results ----------------
@app.post("/studies/{study_id}/classify")
def run_classify(study_id: str, user: User = Depends(sec.require_role("consultant")),
                 db: Session = Depends(get_session)):
    idle_gaps.detect_gaps(db, study_id)
    res = classify_study(db, study_id)
    sec.audit(db, user, "classify", study_id)
    db.commit()
    return res

@app.get("/studies/{study_id}/manload")
def get_manload(study_id: str, va_efficiency: float = 1.0,
                user: User = Depends(sec.require_role("consultant")),
                db: Session = Depends(get_session)):
    sec.audit(db, user, "view_manload", study_id); db.commit()
    return compute_manload(db, study_id, va_efficiency=va_efficiency, persist=False)

@app.post("/studies/{study_id}/train-ml")
def train_ml(study_id: str, user: User = Depends(sec.require_role("consultant")),
             db: Session = Depends(get_session)):
    return ml_classify.train(db, study_id)

@app.get("/studies/{study_id}/validity")
def get_validity(study_id: str, user: User = Depends(sec.require_role("consultant")),
                 db: Session = Depends(get_session)):
    return {"divergences": validity.divergences(db, study_id),
            "peer_outliers": validity.peer_outliers(db, study_id),
            "correction_bias": validity.correction_bias(db, study_id)}

# ---------------- study setup (wizard) ----------------
@app.post("/orgs")
def create_org(body: OrgIn, user: User = Depends(sec.require_role("consultant")),
               db: Session = Depends(get_session)):
    org = Organization(name=body.name)
    db.add(org)
    sec.audit(db, user, "create_org", org.id)
    db.commit()
    return {"id": org.id, "name": org.name}

@app.get("/orgs")
def list_orgs(user: User = Depends(sec.require_role("consultant")),
              db: Session = Depends(get_session)):
    return [{"id": o.id, "name": o.name} for o in db.query(Organization).all()]

@app.post("/studies")
def create_study(body: StudyIn, user: User = Depends(sec.require_role("consultant")),
                 db: Session = Depends(get_session)):
    study = Study(org_id=body.org_id, name=body.name,
                  start_date=body.start_date, end_date=body.end_date,
                  data_scope={"retention_days": body.retention_days})
    db.add(study)
    sec.audit(db, user, "create_study", study.id)
    db.commit()
    return {"id": study.id}

@app.post("/roles")
def create_role(body: RoleIn, user: User = Depends(sec.require_role("consultant")),
                db: Session = Depends(get_session)):
    role = Role(**body.model_dump())
    db.add(role)
    db.commit()
    return {"id": role.id}

@app.post("/volumes")
def add_volume(body: VolumeIn, user: User = Depends(sec.require_role("consultant")),
               db: Session = Depends(get_session)):
    from datetime import date as _date
    vol = Volume(study_id=body.study_id, activity_id=body.activity_id,
                 period=_date.fromisoformat(body.period), count=body.count)
    db.add(vol)
    db.commit()
    return {"ok": True}

@app.post("/studies/{study_id}/standard-times")
def set_standard_time(study_id: str, body: StandardTimeIn,
                      user: User = Depends(sec.require_role("consultant")),
                      db: Session = Depends(get_session)):
    existing = db.query(StandardTime).filter_by(
        study_id=study_id, activity_id=body.activity_id).first()
    if existing:
        existing.std_minutes_per_unit = body.std_minutes_per_unit
        existing.method = body.method
        existing.set_by = user.email
    else:
        db.add(StandardTime(study_id=study_id, activity_id=body.activity_id,
                            std_minutes_per_unit=body.std_minutes_per_unit,
                            method=body.method, set_by=user.email))
    sec.audit(db, user, "set_standard_time", body.activity_id)
    db.commit()
    return {"ok": True}

@app.get("/studies/{study_id}/report/pptx")
def get_pptx(study_id: str, user: User = Depends(sec.require_role("consultant")),
             db: Session = Depends(get_session)):
    from fastapi.responses import FileResponse
    import tempfile
    from reports.generate import generate_pptx
    tmp = tempfile.mktemp(suffix=".pptx")
    generate_pptx(db, study_id, out_path=tmp)
    sec.audit(db, user, "export_pptx", study_id)
    db.commit()
    return FileResponse(tmp, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        filename="study_report.pptx")


# ---------------- admin: retention + audit ----------------
@app.post("/admin/purge")
def purge(user: User = Depends(sec.require_role("client_admin")),
          db: Session = Depends(get_session)):
    return {"purged_studies": scheduler.purge_expired()}

@app.get("/admin/audit")
def audit_log(user: User = Depends(sec.require_role("client_admin")),
              db: Session = Depends(get_session)):
    rows = db.query(AuditLog).order_by(AuditLog.ts.desc()).limit(100).all()
    return [{"ts": r.ts.isoformat(), "role": r.role, "action": r.action, "target": r.target} for r in rows]