"""Retention scheduler (PRD §F4): auto-delete raw events/ESM/blocks N days after a
study closes, keeping only aggregate results. Runs as a background job inside the
API, and can also be invoked manually.
"""
from datetime import datetime, timedelta
from db.database import SessionLocal
from db.models import Study, Participant, ActivityEvent, EsmResponse, ClassifiedBlock


def purge_expired(now=None):
    now = now or datetime.utcnow()
    db = SessionLocal()
    purged = []
    try:
        for study in db.query(Study).all():
            retention_days = (study.data_scope or {}).get("retention_days", 30)
            cutoff = datetime.combine(study.end_date, datetime.min.time()) + timedelta(days=retention_days)
            if study.status == "closed" or now >= cutoff:
                p_ids = [p.id for p in db.query(Participant).filter_by(study_id=study.id).all()]
                if p_ids:
                    db.query(ActivityEvent).filter(ActivityEvent.participant_id.in_(p_ids)).delete(synchronize_session=False)
                    db.query(EsmResponse).filter(EsmResponse.participant_id.in_(p_ids)).delete(synchronize_session=False)
                    db.query(ClassifiedBlock).filter(ClassifiedBlock.participant_id.in_(p_ids)).delete(synchronize_session=False)
                    purged.append(study.id)
        db.commit()
    finally:
        db.close()
    return purged


def start_scheduler():
    """Start APScheduler if available; otherwise no-op (manual purge still works)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception:
        return None
    sched = BackgroundScheduler(daemon=True)
    sched.add_job(purge_expired, "interval", hours=24, id="retention_purge")
    sched.start()
    return sched
