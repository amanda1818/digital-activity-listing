"""Classification engine (PRD Module C).

Pass 1 (rules): match each activity event's app/window keywords to the catalog.
ESM responses that overlap an event OVERRIDE the rule guess for that block.
Pass 2 (Claude): only for events the rules couldn't confidently match, and only
if ANTHROPIC_API_KEY is set. Falls back to rules-only otherwise — the app still
runs end to end with no key.
Divergence (PRD §G2): if the in-the-moment ESM claim conflicts with the passive
signal (e.g. claims value-add work during an idle block), the block is flagged
for human review rather than silently trusted.
"""
import json
from db.models import (
    ActivityEvent, ActivityCatalog, EsmResponse, ClassifiedBlock, Participant, Role,
)
import config


def _catalog_for_family(session, family):
    return session.query(ActivityCatalog).filter_by(role_family=family).all()


def _match_rule(text, catalog_rows):
    """Return (ActivityCatalog, confidence) by keyword substring match, or (None, 0)."""
    t = (text or "").lower()
    for row in catalog_rows:
        for kw in row.keywords:
            if kw.lower() in t:
                return row, 0.95
    return None, 0.0


def _claude_classify(event, candidates):
    """Optional AI pass. Returns (activity_id, classification, confidence) or None."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        options = [{"id": c.id, "name": c.activity_name,
                    "classification": c.default_classification} for c in candidates]
        prompt = (
            "You classify a block of office work. Choose the single best matching "
            "activity from the provided list ONLY. Never invent activities. "
            "Return JSON only: {\"activity_id\":..., \"classification\":\"VA|NVA_necessary|NVA_waste\", "
            "\"confidence\":0-1}.\n\n"
            f"Block metadata: app={event.app_name}, window={event.window_title_hash}, "
            f"category={event.category}, active={event.is_active}.\n"
            f"Candidate activities: {json.dumps(options)}"
        )
        msg = client.messages.create(
            model=config.CLASSIFY_MODEL, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        return data.get("activity_id"), data.get("classification"), float(data.get("confidence", 0.5))
    except Exception:
        return None  # never let the AI pass break the pipeline


def classify_study(session, study_id, use_ai=True):
    """Build classified_blocks for every participant in the study."""
    from engine import ml_classify  # avoid circular at module level

    # clear previous run
    p_ids = [p.id for p in session.query(Participant).filter_by(study_id=study_id).all()]
    if p_ids:
        session.query(ClassifiedBlock).filter(
            ClassifiedBlock.participant_id.in_(p_ids)).delete(synchronize_session=False)
        session.commit()

    cat_by_id = {c.id: c for c in session.query(ActivityCatalog).all()}
    n_blocks, n_review, n_diverge = 0, 0, 0

    for p in session.query(Participant).filter_by(study_id=study_id).all():
        role = session.get(Role, p.role_id)
        catalog_rows = _catalog_for_family(session, role.role_family)
        events = session.query(ActivityEvent).filter_by(participant_id=p.id).order_by(
            ActivityEvent.start_ts).all()
        esm = session.query(EsmResponse).filter_by(participant_id=p.id).all()

        for ev in events:
            minutes = (ev.end_ts - ev.start_ts).total_seconds() / 60.0
            text = f"{ev.app_name} {ev.window_title_hash} {ev.category}"
            # Pass 1: rules
            act, conf = _match_rule(text, catalog_rows)
            # Pass 1.5: trained ML model (reduces AI API calls as data accumulates; PRD §C3.2)
            if act is None:
                ml = ml_classify.predict(text)
                if ml and ml[0] in cat_by_id and ml[1] >= config.CONFIDENCE_REVIEW_THRESHOLD:
                    act = cat_by_id[ml[0]]
                    conf = ml[1]
            # Pass 2: AI only if rules and ML both failed
            if act is None and use_ai:
                ai = _claude_classify(ev, catalog_rows)
                if ai and ai[0] in cat_by_id:
                    act = cat_by_id[ai[0]]
                    conf = ai[2]
            classification = act.default_classification if act else "NVA_waste"
            confidence = conf if act else 0.3
            divergence = ""

            # ESM override (PRD §C1.2) + divergence check (PRD §G2)
            overlap = next((e for e in esm if e.response_ts and ev.start_ts <= e.prompt_ts <= ev.end_ts), None)
            if overlap and overlap.activity_id in cat_by_id:
                claimed = cat_by_id[overlap.activity_id]
                # divergence: claims value-add while the passive signal says idle/mismatch
                if claimed.default_classification == "VA" and (not ev.is_active or ev.category == "idle"):
                    divergence = "esm_vs_passive_mismatch"
                    n_diverge += 1
                act = claimed
                classification = claimed.default_classification
                confidence = max(confidence, 0.8)

            needs_review = (confidence < config.CONFIDENCE_REVIEW_THRESHOLD) or bool(divergence)
            if needs_review:
                n_review += 1

            session.add(ClassifiedBlock(
                participant_id=p.id, activity_id=act.id if act else None,
                start_ts=ev.start_ts, end_ts=ev.end_ts, minutes=minutes,
                classification=classification, confidence=confidence,
                needs_review=needs_review, divergence_flag=divergence,
            ))
            n_blocks += 1
    session.commit()
    return {"blocks": n_blocks, "needs_review": n_review, "divergences": n_diverge}