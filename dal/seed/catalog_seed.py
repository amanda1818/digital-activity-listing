"""Seed activity catalog (PRD Appendix A, expanded). Each activity carries the
keywords the rule-based classifier uses to map raw app/window data back to it.
"""
from db.models import ActivityCatalog

CATALOG = [
    # role_family, activity_name, classification, keywords, is_rework
    ("Finance", "Process invoice", "VA", ["invoice", "ap entry", "process order"], False),
    ("Finance", "Prepare financial report", "VA", ["financial report", "statement", "prepare report"], False),
    ("Finance", "Reconcile ledger", "NVA_necessary", ["reconcile", "ledger", "general ledger", "gl"], False),
    ("Finance", "Compliance check", "NVA_necessary", ["compliance", "audit check", "control check"], False),
    ("Finance", "Correct rejected invoice", "NVA_waste", ["correction", "rejected invoice", "fix invoice", "rework"], True),
    ("Finance", "Wait for approval", "NVA_waste", ["waiting", "pending approval", "blocked"], False),
    ("Finance", "Status meeting", "NVA_necessary", ["meeting", "standup", "briefing", "call"], False),
    ("Finance", "Email / correspondence", "NVA_necessary", ["email", "outlook", "gmail", "inbox"], False),
    ("Finance", "Format / clean report", "NVA_waste", ["format", "cleanup", "reformat", "beautify"], False),
    ("Finance", "Idle / break", "NVA_waste", ["idle", "break", "away"], False),

    ("Management", "Review & approve", "VA", ["approve", "review", "sign off"], False),
    ("Management", "Planning", "VA", ["planning", "strategy", "roadmap"], False),
    ("Management", "Reporting to leadership", "NVA_necessary", ["leadership report", "exec report", "report"], False),
    ("Management", "Team meeting", "NVA_necessary", ["meeting", "briefing", "1:1", "call"], False),
    ("Management", "Email / correspondence", "NVA_necessary", ["email", "outlook", "gmail", "inbox"], False),
    ("Management", "Idle / break", "NVA_waste", ["idle", "break", "away"], False),
]


def seed_catalog(session):
    """Insert the catalog if empty. Returns {(family, name): ActivityCatalog}."""
    existing = session.query(ActivityCatalog).count()
    if existing == 0:
        for fam, name, cls, kw, rework in CATALOG:
            session.add(ActivityCatalog(
                role_family=fam, activity_name=name,
                default_classification=cls, keywords=kw, is_rework_category=rework,
            ))
        session.commit()
    rows = session.query(ActivityCatalog).all()
    return {(r.role_family, r.activity_name): r for r in rows}
