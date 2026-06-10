"""Consultant dashboard (PRD Module D). Run from project root:

    streamlit run dashboard/app.py

Shows manload, VA/NVA split, the load profile across the cycle, the review
queue, divergences, and an interactive standard-efficiency slider that
recomputes the required headcount live.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import pandas as pd
import streamlit as st
from datetime import date, timedelta
from db.database import SessionLocal
from db.models import (Study, ClassifiedBlock, Participant, ActivityCatalog,
                       StandardTime, Role, AuditLog, ActivityEvent,
                       Organization, Volume)
from engine.manload import compute_manload, load_profile
from engine import validity, ml_classify, idle_gaps

st.set_page_config(page_title="Digital Activity Listing", layout="wide")
NAVY = "#1E2761"

s = SessionLocal()
studies = s.query(Study).order_by(Study.created_at.desc()).all()

st.sidebar.title("Digital Activity Listing")

if not studies:
    st.warning("No study found — create one in the **Study setup** tab below.")
    study_id = None
    study = None
    res_df = pd.DataFrame()
else:
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

    if study:
        st.title(study.name)
        st.caption("Required-vs-actual headcount from measured + sampled activity data. Waste is excluded from required time.")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
    ["Manload overview", "Load profile", "Activity & waste", "Review & validity",
     "Standard times", "Admin & ML", "Study setup"])

# ---------- Overview ----------
with tab1:
    if not study_id:
        st.info("Create a study first in the **Study setup** tab.")
    else:
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
    if not rq.empty:
        st.dataframe(rq, use_container_width=True, hide_index=True)
        st.caption("Override a block's classification directly below.")
        with st.form("override_form"):
            block_id = st.number_input("Block ID", min_value=1, step=1)
            new_cls = st.selectbox("New classification", ["VA", "NVA_necessary", "NVA_waste"])
            submitted = st.form_submit_button("Apply override")
            if submitted:
                blk = s.get(ClassifiedBlock, int(block_id))
                if blk:
                    from db.models import EsmCorrection
                    s.add(EsmCorrection(participant_id=blk.participant_id,
                                        old_classification=blk.classification,
                                        new_classification=new_cls))
                    blk.consultant_override = new_cls
                    s.commit()
                    st.success(f"Block {block_id} overridden to {new_cls}.")
                else:
                    st.error("Block not found.")
    else:
        st.dataframe(pd.DataFrame({"info": ["empty"]}), use_container_width=True, hide_index=True)

    st.subheader("Correction-bias indicators (PRD §G4)")
    cb = pd.DataFrame(validity.correction_bias(s, study_id))
    st.dataframe(cb if not cb.empty else pd.DataFrame({"info": ["no directional bias detected"]}),
                 use_container_width=True, hide_index=True)
    if not cb.empty:
        st.warning("Flagged participants always upgrade their own classification. "
                   "Consider cross-referencing their blocks with passive signal data before finalising.")

    st.subheader("Peer outliers (spending > 2× the role median)")
    po = pd.DataFrame(validity.peer_outliers(s, study_id))
    st.dataframe(po if not po.empty else pd.DataFrame({"info": ["none"]}),
                 use_container_width=True, hide_index=True)

# ---------- Standard times ----------
with tab5:
    st.subheader("Standard time per unit")
    cat_all = s.query(ActivityCatalog).all()
    cat = {c.id: c.activity_name for c in cat_all}
    sts = s.query(StandardTime).filter_by(study_id=study_id).all()

    blocks_for_st = (s.query(ClassifiedBlock)
                     .join(Participant, ClassifiedBlock.participant_id == Participant.id)
                     .filter(Participant.study_id == study_id,
                             ClassifiedBlock.classification == "VA").all())
    p25_by_act: dict = {}
    if blocks_for_st:
        bdf = pd.DataFrame([{"activity_id": b.activity_id, "minutes": b.minutes}
                             for b in blocks_for_st if b.activity_id])
        if not bdf.empty:
            p25_by_act = bdf.groupby("activity_id")["minutes"].quantile(0.25).to_dict()

    sdf = pd.DataFrame([{
        "activity": cat.get(x.activity_id, "?"),
        "std_min_per_unit (current)": x.std_minutes_per_unit,
        "suggested p25 (min)": round(p25_by_act.get(x.activity_id, 0), 1),
        "method": x.method,
    } for x in sts])
    st.dataframe(sdf if not sdf.empty else pd.DataFrame({"info": ["run the pipeline first"]}),
                 use_container_width=True, hide_index=True)
    st.caption("'Suggested p25' = 25th-percentile observed VA time across participants — "
               "the efficient-worker benchmark (PRD §D1 percentile method). "
               "Use the efficiency slider in the sidebar to recompute manload live.")

    st.subheader("Override a standard time")
    with st.form("std_time_form"):
        act_options = {c.activity_name: c.id for c in cat_all}
        chosen_act = st.selectbox("Activity", list(act_options.keys()))
        new_std = st.number_input("New std minutes per unit", min_value=0.1, value=30.0, step=0.5)
        method = st.selectbox("Method", ["percentile", "engineered", "waste_stripped"])
        if st.form_submit_button("Save"):
            act_id = act_options[chosen_act]
            existing = s.query(StandardTime).filter_by(study_id=study_id, activity_id=act_id).first()
            if existing:
                existing.std_minutes_per_unit = new_std
                existing.method = method
                existing.set_by = "consultant"
            else:
                s.add(StandardTime(study_id=study_id, activity_id=act_id,
                                   std_minutes_per_unit=new_std, method=method, set_by="consultant"))
            s.commit()
            st.success(f"Standard time for '{chosen_act}' saved.")

    st.subheader("Transaction volumes (for time-per-output anchoring)")
    vol_acts = {c.activity_name: c.id for c in cat_all}
    with st.form("volume_form"):
        v_act = st.selectbox("Activity", list(vol_acts.keys()), key="vol_act")
        v_period = st.date_input("Period (date)", value=date.today())
        v_count = st.number_input("Units produced", min_value=1, step=1)
        if st.form_submit_button("Add volume"):
            s.add(Volume(study_id=study_id, activity_id=vol_acts[v_act],
                         period=v_period, count=int(v_count)))
            s.commit()
            st.success("Volume entry saved.")

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

    st.subheader("Export reports")
    col_docx, col_pptx = st.columns(2)
    with col_docx:
        if st.button("Generate Word report (.docx)"):
            import tempfile
            from reports.generate import generate_report
            tmp = tempfile.mktemp(suffix=".docx")
            generate_report(s, study_id, out_path=tmp)
            with open(tmp, "rb") as f:
                st.download_button("Download .docx", f.read(), file_name="study_report.docx",
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    with col_pptx:
        if st.button("Generate PowerPoint report (.pptx)"):
            import tempfile
            from reports.generate import generate_pptx
            tmp = tempfile.mktemp(suffix=".pptx")
            generate_pptx(s, study_id, out_path=tmp)
            with open(tmp, "rb") as f:
                st.download_button("Download .pptx", f.read(), file_name="study_report.pptx",
                                   mime="application/vnd.openxmlformats-officedocument.presentationml.presentation")

    st.subheader("Audit log (latest 50)")
    rows = s.query(AuditLog).order_by(AuditLog.ts.desc()).limit(50).all()
    adf = pd.DataFrame([{"ts": r.ts, "role": r.role, "action": r.action, "target": r.target[:12]}
                        for r in rows])
    st.dataframe(adf if not adf.empty else pd.DataFrame({"info": ["no activity yet"]}),
                 use_container_width=True, hide_index=True)
    st.caption("Retention: raw events/ESM/blocks auto-purge after the study's retention window "
               "(default 30 days post-close). Run manually via the API: POST /admin/purge.")

# ---------- Study setup wizard ----------
with tab7:
    st.subheader("Create a new study  (PRD §F1)")
    st.caption("Define the study window, roles, and headcount. The wizard warns if your window is "
               "shorter than one full cycle for cyclical functions (PRD §F1.1).")

    orgs = s.query(Organization).all()
    with st.form("study_wizard"):
        st.markdown("**Organisation**")
        org_options = {o.name: o.id for o in orgs}
        new_org = st.text_input("New org name (leave blank to pick existing)")
        if org_options:
            chosen_org = st.selectbox("Or pick existing org", ["— create new —"] + list(org_options.keys()))
        else:
            chosen_org = "— create new —"

        st.markdown("**Study**")
        study_name = st.text_input("Study name", placeholder="e.g. Finance dept — May 2026")
        start_d = st.date_input("Start date", value=date.today())
        end_d = st.date_input("End date", value=date.today() + timedelta(days=30))
        retention = st.number_input("Retention days (raw data deleted N days post-close)", min_value=7, value=30)

        st.markdown("**Roles** — add up to 5 (you can add more via the API)")
        roles_data = []
        for i in range(1, 4):
            st.markdown(f"*Role {i}*")
            c1, c2, c3, c4, c5 = st.columns([3, 2, 1, 1, 1])
            rname = c1.text_input("Name", key=f"rname{i}", placeholder="e.g. Staff Accountant")
            rfam = c2.text_input("Role family", key=f"rfam{i}", placeholder="e.g. Finance")
            rhc = c3.number_input("Headcount", min_value=1, value=2, key=f"rhc{i}")
            rmin = c4.number_input("Min/day", min_value=60, value=420, key=f"rmin{i}")
            rcyc = c5.checkbox("Cyclical?", key=f"rcyc{i}")
            if rname and rfam:
                roles_data.append({"name": rname, "role_family": rfam,
                                   "current_headcount": rhc, "available_minutes_per_day": rmin,
                                   "cyclical": rcyc})

        submitted = st.form_submit_button("Create study")

    if submitted:
        errors = []
        study_days = (end_d - start_d).days
        has_cyclical = any(r["cyclical"] for r in roles_data)
        if has_cyclical and study_days < 28:
            errors.append(f"⚠️ Study window is {study_days} days — cyclical roles require at least "
                          "one full month (28+ days) covering month-end close plus a normal mid-month period (PRD §F1.1).")
        if end_d <= start_d:
            errors.append("End date must be after start date.")
        if not study_name:
            errors.append("Study name is required.")
        if not roles_data:
            errors.append("Add at least one role.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            if new_org:
                org = Organization(name=new_org)
                s.add(org); s.flush()
                org_id = org.id
            elif chosen_org != "— create new —":
                org_id = org_options[chosen_org]
            else:
                st.error("Provide an org name or pick an existing one.")
                st.stop()

            new_study = Study(org_id=org_id, name=study_name,
                              start_date=start_d, end_date=end_d,
                              data_scope={"retention_days": int(retention)})
            s.add(new_study); s.flush()
            for r in roles_data:
                s.add(Role(study_id=new_study.id, **r))
            s.commit()
            st.success(f"Study **{study_name}** created (ID: `{new_study.id}`). "
                       "Refresh the page to see it in the study selector.")
            if has_cyclical and study_days >= 28:
                st.info("Cyclical roles detected — study window spans a full month. "
                        "Baseline vs. peak headcount will be computed automatically.")