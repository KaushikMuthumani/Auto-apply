"""
core/filter.py — Job filter.

Strategy: skip as little as possible. You are a fresher casting a wide net.
Only hard-block roles that are genuinely wrong (senior, manager, etc.)
and roles with no engineering component at all.

Everything else passes — better to apply and get rejected than to
self-filter and miss an opportunity.
"""
from config.settings import SKIP_IF
from telegram.scraper import Job


# Roles that are 100% not software engineering
NON_TECH_ROLES = [
    "fraud analyst", "content analyst", "risk analyst", "credit analyst",
    "financial analyst", "investment analyst", "equity analyst",
    "operations analyst", "compliance analyst", "legal analyst",
    "hr analyst", "talent acquisition", "recruiter", "sales",
    "marketing", "accountant", "finance", "auditor",
    "project associate",   # non-tech project roles
    "associate content",
    "data & analytics analyst",   # business BI, not engineering
    "soc analyst", "l1 soc",       # security operations, not dev
]

def should_apply(job: Job) -> tuple[bool, str]:
    title = job.title.lower().strip()

    # Hard skip — senior/lead/management
    for phrase in SKIP_IF:
        if phrase.lower().rstrip() in title:
            return False, f"senior/lead: {phrase.strip()}"

    # Skip clearly non-tech roles
    for role in NON_TECH_ROLES:
        if role in title:
            return False, f"non-tech role: {role}"

    # Skip if title is basically just punctuation or very short garbage
    clean = title.replace("-", "").replace("_", "").replace(" ", "").strip()
    if len(clean) < 3:
        return False, "title too short/garbage"

    # Skip if title is clearly a company-only parse failure
    # (e.g. "! — Intern" where company is "!")
    if job.company.strip() in ("!", "?", "-", "", "Unknown") and len(title) < 5:
        return False, "bad parse"

    # Everything else passes — fresher casting wide net
    return True, ""
