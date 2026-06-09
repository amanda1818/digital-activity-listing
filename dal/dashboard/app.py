"""Consultant dashboard (PRD Module D). Run from project root:

    streamlit run dashboard/app.py

Shows manload, VA/NVA split, the load profile across the cycle, the review
queue, divergences, and an interactive standard-efficiency slider that
recomputes the required headcount live.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
from db.database import SessionLocal
from db.models import (Study, ClassifiedBlock, Participant, ActivityCatalog,
                       StandardTime, Role, AuditLog, ActivityEvent)
from engine.manload import compute_manload, load_profile
from engine import validity, ml_classify, idle_gaps

st.set_page_config(page_title="Digital Activity Listing", layout="wide")
NAVY = "#1E2761"

s = SessionLocal()
studies = s.query(Study).order_by(Study.created_at.desc()).all()
if not studies:
    st.error("No study found. Run:  python -m scripts.init_db  then  python -m scripts.run_pipeline")
    st.stop()

st.sidebar.title("Digital Activity Listing")
study_names = {f"{st_.name}": st_.id for st_ in studies}
chosen = st.sidebar.selectbox("Study", list(study_names.keys()))
study_id = study_names[chosen]
study = s.get(Study, study_id)

va_eff = st.sidebar.slider(
    "Value-add efficiency (standard pace)", 0.70, 1.00, 1.00, 0.05,
    help="Model 'if value-add work were done at standard pace'. Lower = stricter standard → fewer required heads.",
)
st.sidebar.caption(f"Window: {study.start_date} → {study.end_date}")

results = compute_manload(s, study_id, va_efficiency=va_eff, persist=False)
res_df = pd.DataFrame(results)

st.title(study.name)
st.caption("Required-vs-actual headcount from measured + sampled activity data. Waste is excluded from required time.")

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
    ["Manload overview", "Load profile", "Activity & waste", "Review & validity",
     "Standard times", "Admin & ML"])

# ---------- Overview ----------
with tab1:
    overall = res_df[res_df.period == "overall"]
    cols = st.columns(len(overall))
    for col, (_, r) in zip(cols, overall.iterrows()):
        col.metric(r["role"], f"{r['required_headcount']:.2f} req",
                   f"{r['gap']:+.2f} vs {r['actual_headcount']} actual")
    st.divider()
    st.subheader("Required vs. actual headcount")
    chart_df = overall.set_index("role")[["required_headcount", "actual_headcount"]]
    st.bar_chart(chart_df)
    st.subheader("Time split (VA / NVA-necessary / NVA-waste)")
    split = overall.set_index("role")[["va_pct", "nva_nec_pct", "nva_waste_pct"]]
    split.columns = ["Value-added", "NVA-necessary", "NVA-waste"]
    st.bar_chart(split)

    cyc = res_df[res_df.period.isin(["baseline", "peak"])]
    if not cyc.empty:
        st.subheader("Cyclical roles — baseline vs. peak (month-end)")
        piv = cyc.pivot(index="role", columns="period", values="required_headcount")
        piv["actual"] = overall.set_index("role")["actual_headcount"]
        st.dataframe(piv, use_container_width=True)
        st.info("Peak (month-end close) needs more heads than baseline. Staffing decision: "
                "staff to peak (idle off-peak), staff to average (overtime at peak), or smooth the peak.")

# ---------- Load profile ----------
with tab2:
    st.subheader("Daily required minutes across the cycle")
    lp = load_profile(s, study_id)
    if lp.empty:
        st.write("No data.")
    else:
        st.line_chart(lp)
        st.caption("The rise in the final business days is the month-end close. This is why a cyclical "
                   "study must span a full cycle — a mid-month snapshot would miss it.")

# ---------- Activity & waste ----------
with tab3:
    rows = (s.query(ClassifiedBlock.activity_id, ClassifiedBlock.classification, ClassifiedBlock.minutes)
            .join(Participant, ClassifiedBlock.participant_id == Participant.id)
            .filter(Participant.study_id == study_id).all())
    cat = {c.id: c.activity_name for c in s.query(ActivityCatalog).all()}
    adf = pd.DataFrame(rows, columns=["activity_id", "classification", "minutes"])
    adf["activity"] = adf["activity_id"].map(cat)
    by_act = adf.groupby(["activity", "classification"])["minutes"].sum().reset_index()
    by_act["hours"] = (by_act["minutes"] / 60).round(1)
    st.subheader("Time by activity (hours)")
    st.bar_chart(by_act.groupby("activity")["hours"].sum().sort_values(ascending=False))
    st.subheader("Waste detail")
    waste = by_act[by_act.classification == "NVA_waste"].sort_values("hours", ascending=False)
    st.dataframe(waste[["activity", "hours"]], use_container_width=True, hide_index=True)

# ---------- Review & validity ----------
with tab4:
    st.subheader("Divergences (in-the-moment claim vs. passive signal)")
    div = pd.DataFrame(validity.divergences(s, study_id))
    st.dataframe(div if not div.empty else pd.DataFrame({"info": ["none flagged"]}),
                 use_container_width=True, hide_index=True)
    st.subheader("Review queue (low confidence or flagged)")
    rq = pd.DataFrame(validity.review_queue(s, study_id))
    st.dataframe(rq if not rq.empty else pd.DataFrame({"info": ["empty"]}),
                 use_container_width=True, hide_index=True)
    st.subheader("Peer outliers (spending > 2× the role median)")
    po = pd.DataFrame(validity.peer_outliers(s, study_id))
    st.dataframe(po if not po.empty else pd.DataFrame({"info": ["none"]}),
                 use_container_width=True, hide_index=True)

# ---------- Standard times ----------
with tab5:
    st.subheader("Standard time per unit (informational)")
    sts = s.query(StandardTime).filter_by(study_id=study_id).all()
    cat = {c.id: c.activity_name for c in s.query(ActivityCatalog).all()}
    sdf = pd.DataFrame([{"activity": cat.get(x.activity_id, "?"),
                         "std_min_per_unit": x.std_minutes_per_unit, "method": x.method} for x in sts])
    st.dataframe(sdf if not sdf.empty else pd.DataFrame({"info": ["run the pipeline first"]}),
                 use_container_width=True, hide_index=True)
    st.caption("Use the efficiency slider in the sidebar to model standard-pace value-add work and watch "
               "required headcount change on the overview tab.")

# ---------- Admin & ML ----------
with tab6:
    st.subheader("Study lifecycle")
    c1, c2, c3 = st.columns(3)
    n_part = s.query(Participant).filter_by(study_id=study_id).count()
    pending = sum(len(idle_gaps.pending_for_participant(s, p.id))
                  for p in s.query(Participant).filter_by(study_id=study_id).all())
    consented = s.query(Participant).filter_by(study_id=study_id, consent_status="given").count()
    c1.metric("Participants", n_part)
    c2.metric("Consented", consented)
    c3.metric("Idle gaps awaiting attribution", pending)

    st.subheader("ML classifier")
    st.caption("Train a model on the consultant-reviewed labels to reduce reliance on the AI pass.")
    if st.button("Train ML classifier on this study"):
        res = ml_classify.train(s, study_id)
        st.json(res)

    st.subheader("Audit log (latest 50)")
    rows = s.query(AuditLog).order_by(AuditLog.ts.desc()).limit(50).all()
    adf = pd.DataFrame([{"ts": r.ts, "role": r.role, "action": r.action, "target": r.target[:12]}
                        for r in rows])
    st.dataframe(adf if not adf.empty else pd.DataFrame({"info": ["no activity yet"]}),
                 use_container_width=True, hide_index=True)
    st.caption("Retention: raw events/ESM/blocks auto-purge after the study's retention window "
               "(default 30 days post-close). Run manually via the API: POST /admin/purge.")
