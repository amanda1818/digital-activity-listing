"""Data-validity helpers (PRD Module G): surface where the data may not be
trustworthy so the consultant can follow up — not to accuse individuals.
"""
import pandas as pd
from db.models import ClassifiedBlock, Participant, Role, ActivityCatalog


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
    return [{"participant": pseu, "activity": cat.get(b.activity_id, "?"),
             "classification": b.classification, "confidence": round(b.confidence, 2),
             "flag": b.divergence_flag or "low_confidence", "minutes": round(b.minutes, 1)}
            for b, pseu in rows]


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
