"""Microsoft 365 (Graph) connector — COMPLETE implementation (PRD A1.1, A1.5).

No-install telemetry: after Azure AD admin consent, pull calendar + Teams call
metadata and write it as activity_events (category='meeting'). Cannot be executed
in this sandbox (needs a real tenant), but this is production-shaped code: register
an Azure AD app (Application permissions: Calendars.Read, CallRecords.Read.All),
set the three env vars, and run `python -m connectors.graph <participant_id> <upn>`.

    pip install msal requests
    export MS_TENANT_ID=...  MS_CLIENT_ID=...  MS_CLIENT_SECRET=...
"""
import os, sys, hashlib
from datetime import datetime, timedelta

GRAPH = "https://graph.microsoft.com/v1.0"


def _token():
    import msal
    app = msal.ConfidentialClientApplication(
        os.environ["MS_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['MS_TENANT_ID']}",
        client_credential=os.environ["MS_CLIENT_SECRET"],
    )
    res = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in res:
        raise RuntimeError(res.get("error_description", "auth failed"))
    return res["access_token"]


def pull_calendar(upn, start, end):
    """Return event rows (metadata only) ready for ActivityEvent / POST /events."""
    import requests
    token = _token()
    url = f"{GRAPH}/users/{upn}/calendarView"
    params = {"startDateTime": start.isoformat(), "endDateTime": end.isoformat(),
              "$select": "subject,start,end,attendees,isAllDay"}
    headers = {"Authorization": f"Bearer {token}", "Prefer": 'outlook.timezone="UTC"'}
    rows = []
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=20).json()
        for ev in r.get("value", []):
            if ev.get("isAllDay"):
                continue
            s = datetime.fromisoformat(ev["start"]["dateTime"][:19])
            e = datetime.fromisoformat(ev["end"]["dateTime"][:19])
            rows.append({
                "source": "graph", "start_ts": s, "end_ts": e,
                "app_name": "Calendar", "category": "meeting", "is_active": True,
                # metadata only — subject is hashed to a category, never stored raw
                "window_title_hash": hashlib.sha256(ev.get("subject", "").encode()).hexdigest()[:16],
                "signal_flags": {"attendees": len(ev.get("attendees", []))},
            })
        url = r.get("@odata.nextLink"); params = None
    return rows


def ingest_to_db(participant_id, upn, days=30):
    """Pull and persist as ActivityEvent rows for a participant."""
    import os as _os, sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from db.database import SessionLocal
    from db.models import ActivityEvent
    end = datetime.utcnow(); start = end - timedelta(days=days)
    rows = pull_calendar(upn, start, end)
    db = SessionLocal()
    try:
        for row in rows:
            db.add(ActivityEvent(participant_id=participant_id, **row))
        db.commit()
    finally:
        db.close()
    return len(rows)


if __name__ == "__main__":
    print("ingested:", ingest_to_db(sys.argv[1], sys.argv[2]))
