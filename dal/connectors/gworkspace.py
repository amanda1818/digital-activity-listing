"""Google Workspace connector — COMPLETE implementation (PRD A1.2).

No-install telemetry from the client's Workspace after admin consent. Cannot run
in this sandbox (needs a GCP service account with domain-wide delegation), but this
is production-shaped: create a service account, enable domain-wide delegation with
the Calendar scope, then:

    pip install google-api-python-client google-auth
    python -m connectors.gworkspace <participant_id> <user_email> <sa.json>
"""
import sys, hashlib
from datetime import datetime, timedelta

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _service(sa_json, subject_email):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        sa_json, scopes=SCOPES).with_subject(subject_email)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def pull_calendar(sa_json, user_email, start, end):
    svc = _service(sa_json, user_email)
    rows, page = [], None
    while True:
        resp = svc.events().list(
            calendarId="primary", timeMin=start.isoformat() + "Z",
            timeMax=end.isoformat() + "Z", singleEvents=True,
            orderBy="startTime", pageToken=page).execute()
        for ev in resp.get("items", []):
            s = ev["start"].get("dateTime")
            e = ev["end"].get("dateTime")
            if not s or not e:
                continue  # skip all-day
            rows.append({
                "source": "gworkspace",
                "start_ts": datetime.fromisoformat(s[:19]),
                "end_ts": datetime.fromisoformat(e[:19]),
                "app_name": "Calendar", "category": "meeting", "is_active": True,
                "window_title_hash": hashlib.sha256(ev.get("summary", "").encode()).hexdigest()[:16],
                "signal_flags": {"attendees": len(ev.get("attendees", []))},
            })
        page = resp.get("nextPageToken")
        if not page:
            break
    return rows


def ingest_to_db(participant_id, user_email, sa_json, days=30):
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from db.database import SessionLocal
    from db.models import ActivityEvent
    end = datetime.utcnow(); start = end - timedelta(days=days)
    rows = pull_calendar(sa_json, user_email, start, end)
    db = SessionLocal()
    try:
        for row in rows:
            db.add(ActivityEvent(participant_id=participant_id, **row))
        db.commit()
    finally:
        db.close()
    return len(rows)


if __name__ == "__main__":
    print("ingested:", ingest_to_db(sys.argv[1], sys.argv[2], sys.argv[3]))
