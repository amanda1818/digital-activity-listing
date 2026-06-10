"""Data-validity helpers (PRD Module G): surface where the data may not be
trustworthy so the consultant can follow up — not to accuse individuals.
"""
import pandas as pd
from db.models import ClassifiedBlock, Participant, Role, ActivityCatalog, EsmCorrection


def divergences(session, study_id):
    """Blocks flagged where the in-the-moment claim conflicts with passive signals."""
    rows = (
        session.query(ClassifiedBlock, Participant.pseudonym, Role.name)
        .join(Participant, ClassifiedBlock.participant_id == Participant.id)
        .join(Role, Participant.role_id == Role.id)
        .filter(Participant.study_id == study_id, ClassifiedBlock.divergence_flag != "").all()
    )
    return [{"participant": pseu, "role": role, "when": b.start_ts,
             "minutes": round(b.minutes, 1), "flag": b.divergence_flag} for b, pseu, role in rows]


def review_queue(session, study_id):
    rows = (
        session.query(ClassifiedBlock, Participant.pseudonym)
        .join(Participant, ClassifiedBlock.participant_id == Participant.id)
        .filter(Participant.study_id == study_id, ClassifiedBlock.needs_review == True).all()  # noqa: E712
    )
    cat = {c.id: c.activity_name for c in session.query(ActivityCatalog).all()}
    return [{"block_id": b.id, "participant": pseu, "activity": cat.get(b.activity_id, "?"),
             "classification": b.classification, "confidence": round(b.confidence, 2),
             "flag": b.divergence_flag or "low_confidence", "minutes": round(b.minutes, 1)}
            for b, pseu in rows]


def correction_bias(session, study_id):
    """PRD §G4: detect participants whose corrections are systematically one-directional.

    Returns a list of participants flagged for directional bias — always correcting
    idle/waste → productive, never the reverse. Indicator only; not an accusation.
    """
    p_ids = {p.id: p.pseudonym
             for p in session.query(Participant).filter_by(study_id=study_id).all()}
    corrections = (
        session.query(EsmCorrection)
        .filter(EsmCorrection.participant_id.in_(list(p_ids.keys()))).all()
    )
    if not corrections:
        return []

    df = pd.DataFrame([{
        "pid": c.participant_id,
        "old": c.old_classification,
        "new": c.new_classification,
    } for c in corrections])

    RANK = {"VA": 2, "NVA_necessary": 1, "NVA_waste": 0}
    df["old_rank"] = df["old"].map(RANK)
    df["new_rank"] = df["new"].map(RANK)
    df["direction"] = df["new_rank"] - df["old_rank"]  # >0 = upgrade, <0 = downgrade

    out = []
    for pid, grp in df.groupby("pid"):
        total = len(grp)
        upgrades = (grp["direction"] > 0).sum()
        downgrades = (grp["direction"] < 0).sum()
        if total >= 3 and upgrades > 0 and downgrades == 0:
            out.append({
                "participant": p_ids.get(pid, pid),
                "total_corrections": int(total),
                "upgrades": int(upgrades),
                "downgrades": int(downgrades),
                "bias_indicator": "always_upgrades",
            })
    return out


def peer_outliers(session, study_id, multiple=2.0):
    """Participants spending >`multiple`× the role median on total work — flag for follow-up."""
    rows = (
        session.query(ClassifiedBlock.participant_id, Participant.pseudonym, Role.name, ClassifiedBlock.minutes)
        .join(Participant, ClassifiedBlock.participant_id == Participant.id)
        .join(Role, Participant.role_id == Role.id)
        .filter(Participant.study_id == study_id).all()
    )
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["pid", "pseudonym", "role", "minutes"])
    per_person = df.groupby(["role", "pid", "pseudonym"])["minutes"].sum().reset_index()
    out = []
    for role, grp in per_person.groupby("role"):
        med = grp["minutes"].median()
        for _, r in grp.iterrows():
            if med and r["minutes"] > multiple * med:
                out.append({"participant": r["pseudonym"], "role": role,
                            "minutes": round(r["minutes"], 0), "role_median": round(med, 0)})
    return out