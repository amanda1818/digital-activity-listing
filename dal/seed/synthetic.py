"""Generate a realistic synthetic study so the whole pipeline runs out of the box.

Includes a cyclical accounting function with a month-end spike (more processing,
more rework, more waiting in the final business days) so the load-profile and
peak-vs-baseline manload features have something to show.
"""
import random
from datetime import date, datetime, timedelta
from db.models import (
    Organization, Study, Role, Participant, ActivityEvent, EsmResponse, Volume,
    User, AuthToken, NameMap,
)
from seed.catalog_seed import seed_catalog
from auth import security as sec
import crypto_util

random.seed(42)

# Activity "menus" per role family: (activity_name, base_weight, app_name, mins_range)
FINANCE_MENU = [
    ("Process invoice",          30, "ERP",        (15, 45)),
    ("Reconcile ledger",         15, "Excel",      (20, 60)),
    ("Prepare financial report", 10, "Excel",      (30, 90)),
    ("Compliance check",          8, "ERP",        (10, 30)),
    ("Email / correspondence",   12, "Outlook",    (5, 20)),
    ("Status meeting",            8, "Teams",      (20, 45)),
    ("Format / clean report",     7, "Excel",      (10, 30)),
    ("Correct rejected invoice",  5, "ERP",        (10, 25)),   # rework
    ("Wait for approval",         3, "Browser",    (5, 20)),    # waste
    ("Idle / break",              5, "Idle",       (5, 25)),
]
MGMT_MENU = [
    ("Review & approve",         25, "ERP",        (10, 30)),
    ("Planning",                 15, "Word",       (20, 60)),
    ("Team meeting",             20, "Teams",      (30, 60)),
    ("Reporting to leadership",  12, "PowerPoint", (20, 50)),
    ("Email / correspondence",   18, "Outlook",    (5, 25)),
    ("Idle / break",             10, "Idle",       (5, 20)),
]

# Output activities counted in the volumes table (VA work with a unit)
OUTPUT_ACTIVITIES = {
    "Finance": ["Process invoice", "Prepare financial report"],
    "Management": ["Review & approve"],
}


def _working_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            yield d
        d += timedelta(days=1)


def _keyword_for(catalog_row):
    return catalog_row.keywords[0] if catalog_row.keywords else catalog_row.activity_name.lower()


def generate_demo(session):
    cat = seed_catalog(session)

    org = Organization(name="Demo Client Co.")
    session.add(org); session.flush()

    start = date.today().replace(day=1)          # first of this month
    # study spans a full month (cycle rule) — go to end of month
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)

    study = Study(org_id=org.id, name="Finance Dept Activity Listing",
                  start_date=start, end_date=end, status="active",
                  data_scope={"sources": ["agent", "graph"], "retention_days": 30})
    session.add(study); session.flush()

    roles = [
        Role(study_id=study.id, name="Finance Manager", role_family="Management",
             current_headcount=1, available_minutes_per_day=420, cyclical=False),
        Role(study_id=study.id, name="Senior Accountant", role_family="Finance",
             current_headcount=2, available_minutes_per_day=420, cyclical=True),
        Role(study_id=study.id, name="Staff Accountant", role_family="Finance",
             current_headcount=3, available_minutes_per_day=420, cyclical=True),
    ]
    for r in roles:
        session.add(r)
    session.flush()

    # participants per role (one per head)
    participants = []
    for r in roles:
        for i in range(r.current_headcount):
            p = Participant(study_id=study.id, role_id=r.id,
                            pseudonym=f"{r.name[:3].upper()}-{i+1:02d}")
            session.add(p); participants.append((p, r))
    session.flush()

    wdays = list(_working_days(start, end))
    peak_days = set(wdays[-5:])  # last 5 business days = month-end close

    # daily volume per output activity (spikes at month-end for finance)
    for r in roles:
        for act_name in OUTPUT_ACTIVITIES.get(r.role_family, []):
            act = cat[(r.role_family, act_name)]
            for d in wdays:
                base = 18 if r.role_family == "Finance" else 6
                count = base * (3 if d in peak_days else 1)
                count = int(count * random.uniform(0.8, 1.2)) * r.current_headcount
                session.add(Volume(study_id=study.id, activity_id=act.id, period=d, count=count))

    # generate activity events + ESM per participant per working day
    for p, r in participants:
        menu = FINANCE_MENU if r.role_family == "Finance" else MGMT_MENU
        for d in wdays:
            peak = d in peak_days and r.cyclical
            day_start = datetime(d.year, d.month, d.day, 8, 30)
            t = day_start
            target_min = r.available_minutes_per_day + random.randint(-20, 30)
            if peak:
                target_min += random.randint(60, 150)  # overtime at close
            spent = 0
            day_events = []
            while spent < target_min:
                # weight rework/waiting up during peak
                weights = []
                for name, w, app, rng in menu:
                    ww = w
                    if peak and name in ("Process invoice", "Correct rejected invoice", "Wait for approval", "Reconcile ledger"):
                        ww *= 2.2
                    weights.append(ww)
                name, _, app, rng = random.choices(menu, weights=weights, k=1)[0]
                dur = random.randint(*rng)
                act = cat[(r.role_family, name)]
                is_idle = (name == "Idle / break")
                category = "meeting" if "meeting" in name.lower() else ("idle" if is_idle else "work")
                ev = ActivityEvent(
                    participant_id=p.id, source="agent",
                    start_ts=t, end_ts=t + timedelta(minutes=dur),
                    app_name=app, window_title_hash=_keyword_for(act),
                    category=category, is_active=not is_idle,
                    signal_flags={"rework": act.is_rework_category},
                )
                session.add(ev); day_events.append((ev, act))
                t += timedelta(minutes=dur)
                spent += dur

            # 3-5 ESM responses sampled across the day
            for _ in range(random.randint(3, 5)):
                if not day_events:
                    break
                ev, act = random.choice(day_events)
                prompt_ts = ev.start_ts + timedelta(minutes=random.randint(0, 5))
                # mostly truthful; small chance of a favourable divergence
                claimed = act
                if random.random() < 0.12 and act.default_classification != "VA":
                    # claim a VA activity instead (creates a divergence to detect)
                    va = cat.get((r.role_family, "Process invoice")) or cat.get((r.role_family, "Review & approve"))
                    claimed = va or act
                session.add(EsmResponse(
                    participant_id=p.id, prompt_ts=prompt_ts,
                    response_ts=prompt_ts + timedelta(seconds=random.randint(3, 8)),
                    activity_id=claimed.id,
                    is_rework=act.is_rework_category or (random.random() < 0.05),
                    is_waiting=(act.activity_name == "Wait for approval"),
                    is_new_request=(random.random() < 0.08),
                ))

    session.commit()

    # --- accounts, tokens, encrypted name map (PRD §F3, §8) ---
    consultant = sec.create_user(session, "consultant@demo", "demo1234", "consultant", org_id=org.id)
    sec.create_user(session, "admin@demo", "demo1234", "client_admin", org_id=org.id)
    consultant_token = sec.issue_token(session, consultant)
    fake_names = ["Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hadi"]
    sample_url = None
    for idx, (p, r) in enumerate(participants):
        if idx == 0:
            p.consent_status = "pending"  # demo the consent screen on the first participant
        u = sec.create_user(session, f"{p.pseudonym.lower()}@demo", "demo1234", "participant",
                            org_id=org.id, participant_id=p.id)
        tok = sec.issue_token(session, u, days=60)
        session.add(NameMap(study_id=study.id, participant_id=p.id,
                            encrypted_name=crypto_util.encrypt(f"{fake_names[idx % len(fake_names)]} ({p.pseudonym})")))
        if sample_url is None:
            sample_url = f"http://127.0.0.1:8000/esm-app?token={tok}"
    session.commit()
    return {"study_id": study.id, "consultant_token": consultant_token, "sample_esm_url": sample_url}
