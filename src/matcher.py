"""Job matching, history tracking, and resume parsing."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

HISTORY_FILE = Path("data/history.json")
SEEN_FILE = Path("data/seen_ids.json")


def extract_resume_text(resume_path: Path) -> str:
    """Extract text from a PDF resume."""
    text_parts = []
    with pdfplumber.open(resume_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def matches_target_roles(job_title: str, target_roles: list[str]) -> bool:
    """Check if a job title matches any target role keywords (case-insensitive)."""
    title_lower = job_title.lower()
    return any(role.lower() in title_lower for role in target_roles)


def load_seen_ids() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen_ids(seen: set[str]):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def load_history() -> list[dict]:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return []


def save_application(record: dict):
    """Append an application record to history."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = load_history()
    history.append(record)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, default=str))


def make_record(
    posting_id: str,
    job_title: str,
    company: str,
    ats_score: int,
    reasoning: str,
    cover_letter: str,
    status: str,
    error: str = "",
) -> dict:
    return {
        "posting_id": posting_id,
        "job_title": job_title,
        "company": company,
        "ats_score": ats_score,
        "reasoning": reasoning,
        "cover_letter": cover_letter,
        "status": status,
        "error": error,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
