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


US_INDICATORS = {"us", "usa", "united states"}
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}
US_CITIES = {
    "san francisco", "new york", "los angeles", "chicago", "seattle",
    "austin", "boston", "denver", "atlanta", "miami", "dallas",
    "houston", "phoenix", "philadelphia", "san diego", "san jose",
    "portland", "minneapolis", "detroit", "salt lake city", "raleigh",
    "charlotte", "nashville", "pittsburgh", "columbus", "indianapolis",
    "remote, us", "remote, united states", "remote - us",
}


def is_us_job(job: dict) -> bool:
    """Check if a job posting is located in the USA."""
    # Lever API provides a 'country' field on some postings
    country = (job.get("country") or "").strip().upper()
    if country in ("US", "USA"):
        return True

    location = (job.get("categories", {}).get("location") or "").lower()
    if not location:
        return False

    if any(ind in location for ind in US_INDICATORS):
        return True
    if "remote" in location and not any(
        x in location for x in ("uk", "canada", "europe", "india", "apac", "emea", "latam",
                                 "spain", "poland", "germany", "france", "ireland", "netherlands",
                                 "brazil", "mexico", "australia", "japan", "singapore", "israel",
                                 "portugal", "italy", "argentina", "colombia", "chile", "sweden",
                                 "denmark", "norway", "finland", "czech", "romania", "hungary",
                                 "austria", "switzerland", "belgium", "south africa", "nigeria",
                                 "turkey", "korea", "taiwan", "philippines", "vietnam", "thailand",
                                 "indonesia", "malaysia", "new zealand", "global")
    ):
        return True
    if any(state in location for state in US_STATES):
        return True
    if any(city in location for city in US_CITIES):
        return True
    return False


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
    platform: str = "lever",
) -> dict:
    return {
        "posting_id": posting_id,
        "job_title": job_title,
        "company": company,
        "platform": platform,
        "ats_score": ats_score,
        "reasoning": reasoning,
        "cover_letter": cover_letter,
        "status": status,
        "error": error,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
