"""Manload engine (PRD Module D / §7).

Model used in this MVP = waste-stripped, time-anchored, role-centric:

    required_minutes(role, period) = Σ ( VA_minutes × va_efficiency + NVA_necessary_minutes )
    one_person_capacity            = available_minutes_per_day × working_days_in_period
    required_headcount             = required_minutes ÷ one_person_capacity
    gap                            = required_headcount − current_headcount

Waste (rework, waiting, idle, over-formatting) is excluded from required time,
so the result shows how many people the *real* work needs. `va_efficiency`
(0.7–1.0) lets the consultant model "if value-add work were done at standard
pace" and recompute live from the dashboard.

Cyclical roles (e.g. accounting) are reported as baseline vs. peak, with peak
days detected from the volume data, plus an overall figure.
"""
import pandas as pd
from db.models import (
    ClassifiedBlock, Participant, Role, Volume, ActivityCatalog, StandardTime,
    ManloadResult, Study,
)


def _blocks_df(session, study_id):
    rows = (
        session.query(ClassifiedBlock, Participant.role_id)
        .join(Participant, ClassifiedBlock.participant_id == Participant.id)
        .filter(Participant.study_id == study_id).all()
    )
    data = []
    for b, role_id in rows:
        cls = b.consultant_override or b.classification
        data.append({
            "role_id": role_id, "participant_id": b.participant_id,
            "date": b.start_ts.date(), "minutes": b.minutes,
            "classification": cls,
        })
    return pd.DataFrame(data)


def _peak_days(session, study_id):
    """Detect peak (busy) days from total daily output volume; top quartile = peak."""
    vols = session.query(Volume).filter_by(study_id=study_id).all()
    if not vols:
        return set()
    df = pd.DataFrame([{"date": v.period, "count": v.count} for v in vols])
    daily = df.groupby("date")["count"].sum()
    if daily.empty:
        return set()
    threshold = daily.quantile(0.75)
    return set(daily[daily >= threshold].index)


def _required_minutes(df, va_efficiency):
    va = df.loc[df.classification == "VA", "minutes"].sum() * va_efficiency
    nec = df.loc[df.classification == "NVA_necessary", "minutes"].sum()
    return va + nec


def _va_split(df):
    total = df["minutes"].sum()
    if total == 0:
        return 0.0, 0.0, 0.0
    va = df.loc[df.classification == "VA", "minutes"].sum() / total * 100
    nec = df.loc[df.classification == "NVA_necessary", "minutes"].sum() / total * 100
    waste = df.loc[df.classification == "NVA_waste", "minutes"].sum() / total * 100
    return va, nec, waste


def compute_manload(session, study_id, va_efficiency=1.0, persist=True):
    df = _blocks_df(session, study_id)
    peak = _peak_days(session, study_id)
    roles = {r.id: r for r in session.query(Role).filter_by(study_id=study_id).all()}

    if persist:
        session.query(ManloadResult).filter_by(study_id=study_id).delete()
        session.commit()

    results = []
    for role_id, role in roles.items():
        rdf = df[df.role_id == role_id] if not df.empty else df
        periods = {"overall": rdf}
        if role.cyclical and peak:
            periods["peak"] = rdf[rdf["date"].isin(peak)] if not rdf.empty else rdf
            periods["baseline"] = rdf[~rdf["date"].isin(peak)] if not rdf.empty else rdf

        for label, pdf in periods.items():
            if pdf is None or pdf.empty:
                continue
            req_min = _required_minutes(pdf, va_efficiency)
            n_days = pdf["date"].nunique()
            capacity = role.available_minutes_per_day * max(n_days, 1)
            required_hc = req_min / capacity if capacity else 0.0
            va, nec, waste = _va_split(pdf)
            res = {
                "role": role.name, "role_id": role_id, "period": label,
                "required_headcount": round(required_hc, 2),
                "actual_headcount": role.current_headcount,
                "gap": round(required_hc - role.current_headcount, 2),
                "va_pct": round(va, 1), "nva_nec_pct": round(nec, 1), "nva_waste_pct": round(waste, 1),
            }
            results.append(res)
            if persist:
                session.add(ManloadResult(
                    study_id=study_id, role_id=role_id, period_label=label,
                    required_headcount=required_hc, actual_headcount=role.current_headcount,
                    gap=required_hc - role.current_headcount,
                    va_pct=va, nva_nec_pct=nec, nva_waste_pct=waste,
                ))
    if persist:
        _store_standard_times(session, study_id, df)
        session.commit()
    return results


def _store_standard_times(session, study_id, df):
    """Informational std minutes-per-unit for output activities (VA work with volume)."""
    session.query(StandardTime).filter_by(study_id=study_id).delete()
    vols = session.query(Volume).filter_by(study_id=study_id).all()
    units_by_act = {}
    for v in vols:
        units_by_act[v.activity_id] = units_by_act.get(v.activity_id, 0) + v.count
    # map VA minutes to activities via the catalog name on the blocks is not stored here,
    # so this is a study-level informational estimate using total VA minutes / total units.
    if df.empty:
        return
    va_min = df.loc[df.classification == "VA", "minutes"].sum()
    total_units = sum(units_by_act.values()) or 1
    for act_id, units in units_by_act.items():
        share = units / total_units
        std = (va_min * share) / units if units else 0
        session.add(StandardTime(
            study_id=study_id, activity_id=act_id,
            std_minutes_per_unit=round(std, 2), method="percentile", set_by="system",
        ))


def load_profile(session, study_id):
    """Daily required minutes per role across the cycle (for the load-profile chart)."""
    df = _blocks_df(session, study_id)
    if df.empty:
        return pd.DataFrame()
    roles = {r.id: r.name for r in session.query(Role).filter_by(study_id=study_id).all()}
    df["role"] = df["role_id"].map(roles)
    df["required"] = 0.0
    df.loc[df.classification == "VA", "required"] = df["minutes"]
    df.loc[df.classification == "NVA_necessary", "required"] = df["minutes"]
    daily = df.groupby(["date", "role"])["required"].sum().reset_index()
    return daily.pivot(index="date", columns="role", values="required").fillna(0)
