# Digital Activity Listing — complete app

A working implementation of the tool specified in `PRD_Digital_Activity_Listing.md`.
It runs end to end on synthetic data (including a cyclical accounting month-end peak),
with auth, consent, the participant ESM check-in app, idle-gap attribution, the
classification + manload engines, an ML classifier, a consultant dashboard, a report
generator, retention/audit, and field-level encryption.

**Principle:** measure the measurable, sample the judgmental, compute the analytics —
metadata only, never keystrokes / screenshots / content.

---

## 1. Quick start (≈3 minutes)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m scripts.init_db            # tables + catalog + demo study + demo accounts
python -m scripts.run_pipeline       # idle-gap detect + classify + manload + train ML

streamlit run dashboard/app.py       # consultant dashboard  → http://localhost:8501
uvicorn api.main:app --reload        # API + ESM app         → http://127.0.0.1:8000/docs
python -m reports.generate           # writes study_report.docx
```

`init_db` prints demo logins and a ready-to-use **ESM link**:
- Consultant: `consultant@demo / demo1234`
- Client admin: `admin@demo / demo1234`
- Participant ESM app: open the printed `http://127.0.0.1:8000/esm-app?token=...` while the API runs.

No API key needed to run. To enable the AI classification pass, set `ANTHROPIC_API_KEY`
in `.env` (the engine works rules-only without it). To set a real encryption key, set
`DAL_ENC_KEY` (see `.env.example`).

A pre-seeded `dal.db` and `model.joblib` are included, so the dashboard shows real numbers
immediately. Re-run `init_db` to regenerate fresh.

---

## 2. What the demo shows

Finance department, one full month, three roles (Manager + two cyclical accountant roles
with a month-end close in the last 5 business days). Expected:

- Overall required ≈ actual headcount.
- **Baseline (mid-month)** required < actual → slack off-peak.
- **Peak (month-end)** required > actual → short ~0.3–0.5 of a head per role.

The ESM app demonstrates: consent gate (the first participant starts "pending"), the
5-second activity check-in, and idle-gap attribution ("you were away — meeting/briefing/…").

---

## 3. Project layout

```
config.py / crypto_util.py / scheduler.py     # settings, field encryption, retention job
db/                  models + engine/session
auth/security.py     PBKDF2 passwords, tokens, role-based access (PRD F3)
seed/                activity catalog + synthetic data + demo accounts
engine/classify.py   rules + Claude classification, ESM override, divergence
engine/manload.py    manload + load profile + baseline/peak
engine/idle_gaps.py  idle-gap detection + attribution (PRD B4)
engine/ml_classify.py scikit-learn classifier (PRD C3.2)
engine/validity.py   divergences, review queue, peer outliers (PRD G)
api/main.py          full API: auth, consent, ESM, ingestion, results, ML, audit, retention
esm_app/page.py      participant ESM web app (served at /esm-app)
dashboard/app.py     consultant dashboard (6 tabs incl Admin & ML)
reports/generate.py  Word study report (PRD E)
connectors/graph.py  Microsoft 365 connector (complete; needs tenant creds)
connectors/gworkspace.py  Google Workspace connector (complete; needs GCP creds)
agent/agent.py       desktop agent: Windows/macOS/Linux + --simulate for local testing
scripts/             init_db, run_pipeline
```

---

## 4. Status

### ✅ Built and tested in this environment
Data model; auth + role-based access (verified 401/403); consent flow; participant
**ESM web app**; **idle-gap attribution**; classification (rules + optional Claude);
manload + load profile + baseline/peak; **ML classifier** (trains to ~0.88 on the demo);
validity (divergences/outliers); consultant dashboard (6 tabs); Word report; **audit log**;
**retention purge**; **field-level encryption** of the name map; desktop agent `--simulate`.

### ✅ Complete code, but NOT executable in this sandbox (need external access)
- `connectors/graph.py` — Microsoft 365 pull (needs an Azure AD app + tenant).
- `connectors/gworkspace.py` — Google Workspace pull (needs a GCP service account).
- `agent/agent.py` real capture loop — needs a Windows/macOS/Linux desktop with input access
  (the `--simulate` path is tested here; the per-OS window/idle calls are written and ready).

### 🔲 Production hardening still recommended before real client data
- Move to PostgreSQL (set `DATABASE_URL`); models are already compatible.
- HTTPS/TLS termination, secrets management, and a real `DAL_ENC_KEY`.
- Per-OS testing + code-signing + PyInstaller packaging of the agent.
- DPA templates and the formal consent record retention policy.

---

## 5. Try the full flow locally
1. `python -m scripts.init_db` then `python -m scripts.run_pipeline`
2. `uvicorn api.main:app --reload`
3. Open the printed ESM link → consent → submit a check-in → attribute an idle gap.
4. (Optional) simulate agent data:  `python agent/agent.py --simulate --participant <id>`
5. `streamlit run dashboard/app.py` → see manload, load profile, validity, Admin & ML.

## 6. PostgreSQL
```bash
pip install "psycopg[binary]"
export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/dal"
python -m scripts.init_db
```

## 7. Privacy mechanics in place
Metadata only; window titles hashed; pseudonymous participants; encrypted name map;
role-aggregated reporting; audit log; retention purge endpoint + scheduler. The consent
UI, encryption-at-rest key management, and scheduled deletion are wired — review against
local law (e.g. Indonesia PDP Law) before production.
