"""Core orchestrator for the auto-apply pipeline."""

import logging
import os
from pathlib import Path

import yaml

from .lever_client import LeverClient
from .matcher import (
    extract_resume_text,
    load_seen_ids,
    make_record,
    matches_target_roles,
    save_application,
    save_seen_ids,
)
from .notifier import send_summary_email
from .scorer import ClaudeScorer

logger = logging.getLogger(__name__)


def load_config(profile_path: str) -> dict:
    with open(profile_path) as f:
        return yaml.safe_load(f)


def load_companies(companies_path: str = "companies.yaml") -> list[str]:
    with open(companies_path) as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def run_pipeline(profile_path: str, dry_run: bool = False):
    """Execute one full pipeline run."""
    config = load_config(profile_path)
    companies = load_companies()

    api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.error("No Anthropic API key configured. Set anthropic_api_key in profile or ANTHROPIC_API_KEY env var.")
        return

    resume_path = Path(config["resume_path"]).expanduser()
    if not resume_path.exists():
        logger.error("Resume not found at %s", resume_path)
        return

    logger.info("Extracting resume text from %s", resume_path)
    resume_text = extract_resume_text(resume_path)
    if not resume_text.strip():
        logger.error("Could not extract text from resume PDF")
        return

    lever = LeverClient()
    scorer = ClaudeScorer(api_key)
    seen_ids = load_seen_ids()
    target_roles = config.get("target_roles", [])
    threshold = config.get("ats_threshold", 75)
    results = []

    name = f"{config['first_name']} {config['last_name']}"
    urls = {}
    if config.get("linkedin_url"):
        urls["LinkedIn"] = config["linkedin_url"]
    if config.get("github_url"):
        urls["GitHub"] = config["github_url"]
    if config.get("website_url"):
        urls["Portfolio"] = config["website_url"]

    consent = config.get("consent", {"marketing": True, "store": True})

    logger.info("Scanning %d companies for matching roles...", len(companies))

    for company in companies:
        jobs = lever.list_jobs(company)
        if not jobs:
            continue

        matching = [j for j in jobs if matches_target_roles(j.get("text", ""), target_roles)]
        new_matching = [j for j in matching if j["id"] not in seen_ids]

        if new_matching:
            logger.info("[%s] Found %d new matching jobs", company, len(new_matching))

        for job in new_matching:
            posting_id = job["id"]
            job_title = job.get("text", "Unknown")
            description = job.get("descriptionPlain", "") or job.get("description", "")

            logger.info("  Scoring: %s @ %s", job_title, company)
            score_result = scorer.score_ats(resume_text, description)
            score = score_result.get("score", 0)
            reasoning = score_result.get("reasoning", "")

            seen_ids.add(posting_id)

            if score < threshold:
                logger.info("  Score %d < %d, skipping", score, threshold)
                record = make_record(posting_id, job_title, company, score, reasoning, "", "skipped")
                results.append(record)
                save_application(record)
                continue

            logger.info("  Score %d >= %d, generating cover letter...", score, threshold)
            cover_letter = scorer.generate_cover_letter(resume_text, job_title, company, description)

            if dry_run:
                logger.info("  [DRY RUN] Would apply to: %s @ %s", job_title, company)
                logger.info("  ATS Score: %d — %s", score, reasoning)
                logger.info("  Cover Letter Preview:\n%s\n", cover_letter[:500])
                record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "dry_run")
                results.append(record)
                save_application(record)
                continue

            logger.info("  Submitting application...")
            resp = lever.apply(
                site=company,
                posting_id=posting_id,
                name=name,
                email=config["email"],
                phone=config.get("phone", ""),
                org=config.get("current_company", ""),
                resume_path=resume_path,
                urls=urls,
                comments=cover_letter,
                consent=consent,
            )

            if resp.get("ok"):
                logger.info("  ✅ Applied! Application ID: %s", resp.get("applicationId"))
                record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "submitted")
            else:
                error = resp.get("error", "unknown")
                logger.warning("  ❌ Failed: %s", error)
                record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "failed", error)

            results.append(record)
            save_application(record)

    save_seen_ids(seen_ids)

    # Summary
    submitted = sum(1 for r in results if r["status"] == "submitted")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    dry = sum(1 for r in results if r["status"] == "dry_run")

    logger.info("=" * 50)
    logger.info("Run complete: %d evaluated, %d submitted, %d skipped, %d failed, %d dry-run",
                len(results), submitted, skipped, failed, dry)

    if not dry_run:
        send_summary_email(config, results)

    return results
