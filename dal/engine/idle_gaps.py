"""Idle-gap attribution (PRD §B4): off-screen ad-hoc meetings/briefings/calls.

detect_gaps() flags idle blocks (and unrecorded gaps between events) above the
threshold that are NOT covered by a scheduled meeting, so the ESM app can ask the
one-tap return question. attribute_gap() applies the participant's answer.
"""
from datetime import timedelta
from db.models import ActivityEvent, Participant
import config

# map the one-tap answer to (category, classification-hint)
ATTRIBUTION_CHOICES = ["meeting", "briefing", "break", "phone_call", "other"]


def detect_gaps(session, study_id):
    """Mark idle/uncovered blocks needing attribution. Returns count flagged."""
    flagged = 0
    threshold = timedelta(minutes=config.IDLE_THRESHOLD_MIN)
    for p in session.query(Participant).filter_by(study_id=study_id).all():
        events = (session.query(ActivityEvent)
                  .filter_by(participant_id=p.id)
                  .order_by(ActivityEvent.start_ts).all())
        meetings = [(e.start_ts, e.end_ts) for e in events if e.category == "meeting"]
        for e in events:
            dur = e.end_ts - e.start_ts
            is_idle = (not e.is_active) or e.category == "idle"
            covered = any(ms <= e.start_ts <= me for ms, me in meetings)
            if is_idle and dur >= threshold and not covered and e.category != "meeting":
                if not e.needs_attribution:
                    e.needs_attribution = True
                    flagged += 1
    session.commit()
    return flagged


def pending_for_participant(session, participant_id):
    rows = (session.query(ActivityEvent)
            .filter_by(participant_id=participant_id, needs_attribution=True)
            .order_by(ActivityEvent.start_ts).all())
    return [{"event_id": e.id, "start": e.start_ts.isoformat(),
             "end": e.end_ts.isoformat(),
             "minutes": round((e.end_ts - e.start_ts).total_seconds() / 60, 1)} for e in rows]


def attribute_gap(session, event_id, choice):
    e = session.get(ActivityEvent, event_id)
    if not e:
        return False
    e.category = choice if choice in ATTRIBUTION_CHOICES else "other"
    e.needs_attribution = False
    # a meeting/briefing/call is real working time; a break stays idle
    e.is_active = choice in ("meeting", "briefing", "phone_call")
    session.commit()
    return True
