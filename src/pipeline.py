"""Core orchestrator for the auto-apply pipeline."""

import logging
import os
from pathlib import Path

import yaml

from .ashby_browser_apply import AshbyBrowserApplier
from .ashby_client import AshbyClient
from .browser_apply import BrowserApplier
from .greenhouse_browser_apply import GreenhouseBrowserApplier
from .greenhouse_client import GreenhouseClient
from .lever_client import LeverClient
from .matcher import (
    extract_resume_text,
    is_us_job,
    load_seen_ids,
    make_record,
    matches_target_roles,
    save_application,
    save_seen_ids,
)
from .notifier import send_summary_email
from .scorer import create_scorer

logger = logging.getLogger(__name__)


def load_config(profile_path: str) -> dict:
    with open(profile_path) as f:
        return yaml.safe_load(f)


def load_companies(companies_path: str = "companies.yaml") -> dict:
    """Load companies grouped by platform.

    Returns {'lever': [...], 'greenhouse': [...]}.
    Supports both old flat list format and new grouped format.
    """
    with open(companies_path) as f:
        data = yaml.safe_load(f)

    # Support old flat format: {companies: [...]}
    if "companies" in data and isinstance(data["companies"], list):
        return {"lever": data["companies"], "greenhouse": []}

    return {
        "lever": data.get("lever", []),
        "greenhouse": data.get("greenhouse", []),
        "ashby": data.get("ashby", []),
    }


def run_pipeline(profile_path: str, dry_run: bool = False, platform: str = "all", backend: str = "local"):
    """Execute one full pipeline run.

    Args:
        profile_path: path to profile YAML
        dry_run: if True, don't submit applications
        platform: 'lever', 'greenhouse', or 'all'
        backend: 'local' (kiro-cli, free) or 'anthropic' (API key required)
    """
    config = load_config(profile_path)
    companies = load_companies()

    api_key = ""
    if backend == "anthropic":
        api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.error("No Anthropic API key configured. Set ANTHROPIC_API_KEY env var or use --backend local.")
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

    scorer = create_scorer(backend=backend, api_key=api_key)
    seen_ids = load_seen_ids()
    target_roles = config.get("target_roles", [])
    threshold = config.get("ats_threshold", 75)
    results = []

    lever_browser = None
    gh_browser = None
    ashby_browser = None

    try:
        if platform in ("lever", "all") and companies["lever"]:
            lever = LeverClient()
            if not dry_run:
                lever_browser = BrowserApplier()
            lever_results = _scan_lever(
                companies["lever"], lever, lever_browser, scorer,
                config, resume_text, seen_ids, target_roles, threshold, dry_run,
            )
            results.extend(lever_results)

        if platform in ("greenhouse", "all") and companies["greenhouse"]:
            gh_client = GreenhouseClient()
            if not dry_run:
                gh_browser = GreenhouseBrowserApplier()
            gh_results = _scan_greenhouse(
                companies["greenhouse"], gh_client, gh_browser, scorer,
                config, resume_text, seen_ids, target_roles, threshold, dry_run,
            )
            results.extend(gh_results)

        if platform in ("ashby", "all") and companies["ashby"]:
            ashby_client = AshbyClient()
            if not dry_run:
                ashby_browser = AshbyBrowserApplier()
            else:
                ashby_browser = None
            ashby_results = _scan_ashby(
                companies["ashby"], ashby_client, ashby_browser, scorer,
                config, resume_text, seen_ids, target_roles, threshold, dry_run,
            )
            results.extend(ashby_results)

    finally:
        if lever_browser:
            lever_browser.quit()
        if gh_browser:
            gh_browser.quit()
        if ashby_browser:
            ashby_browser.quit()

    save_seen_ids(seen_ids)

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


def _process_job(
    posting_id, job_title, company, description, platform_name,
    scorer, config, resume_text, seen_ids, threshold, dry_run,
    submit_fn,
):
    """Score and optionally apply to a single job. Returns a record dict."""
    logger.info("  Scoring: %s @ %s [%s]", job_title, company, platform_name)
    score_result = scorer.score_ats(resume_text, description)
    score = score_result.get("score", 0)
    reasoning = score_result.get("reasoning", "")

    seen_ids.add(posting_id)
    save_seen_ids(seen_ids)

    if score < threshold:
        logger.info("  Score %d < %d, skipping", score, threshold)
        record = make_record(posting_id, job_title, company, score, reasoning, "", "skipped", platform=platform_name)
        save_application(record)
        return record

    logger.info("  Score %d >= %d, generating cover letter...", score, threshold)
    cover_letter = scorer.generate_cover_letter(resume_text, job_title, company, description)

    if dry_run:
        logger.info("  [DRY RUN] Would apply to: %s @ %s", job_title, company)
        record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "dry_run", platform=platform_name)
        save_application(record)
        return record

    logger.info("  Submitting application via browser...")
    resp = submit_fn(cover_letter)

    if resp.get("ok"):
        logger.info("  ✅ Applied: %s @ %s", job_title, company)
        record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "submitted", platform=platform_name)
    else:
        error = resp.get("error", "unknown")
        logger.warning("  ❌ Failed: %s", error)
        record = make_record(posting_id, job_title, company, score, reasoning, cover_letter, "failed", error, platform=platform_name)

    save_application(record)
    return record


def _scan_lever(companies, lever, browser, scorer, config, resume_text, seen_ids, target_roles, threshold, dry_run):
    results = []
    logger.info("Scanning %d Lever companies...", len(companies))

    for company in companies:
        jobs = lever.list_jobs(company)
        if not jobs:
            continue

        matching = [j for j in jobs if matches_target_roles(j.get("text", ""), target_roles) and is_us_job(j)]
        new_matching = [j for j in matching if j["id"] not in seen_ids]

        if new_matching:
            logger.info("[%s] Found %d new matching Lever jobs", company, len(new_matching))

        for job in new_matching:
            def submit_fn(cl, c=company, pid=job["id"]):
                return browser.apply(company=c, posting_id=pid, profile=config, cover_letter=cl)

            record = _process_job(
                job["id"], job.get("text", "Unknown"), company,
                job.get("descriptionPlain", "") or job.get("description", ""),
                "lever", scorer, config, resume_text, seen_ids, threshold, dry_run,
                submit_fn,
            )
            results.append(record)

    return results


def _scan_greenhouse(boards, gh_client, browser, scorer, config, resume_text, seen_ids, target_roles, threshold, dry_run):
    results = []
    logger.info("Scanning %d Greenhouse boards...", len(boards))

    for board in boards:
        jobs = gh_client.list_jobs(board)
        if not jobs:
            continue

        matching = [j for j in jobs if matches_target_roles(j.get("text", ""), target_roles) and is_us_job(j)]
        new_matching = [j for j in matching if j["id"] not in seen_ids]

        if new_matching:
            logger.info("[%s] Found %d new matching Greenhouse jobs", board, len(new_matching))

        for job in new_matching:
            def submit_fn(cl, j=job):
                return browser.apply(job=j, profile=config, cover_letter=cl)

            record = _process_job(
                job["id"], job.get("text", "Unknown"), board,
                job.get("descriptionPlain", "") or job.get("description", ""),
                "greenhouse", scorer, config, resume_text, seen_ids, threshold, dry_run,
                submit_fn,
            )
            results.append(record)

    return results


def _scan_ashby(boards, ashby_client, browser, scorer, config, resume_text, seen_ids, target_roles, threshold, dry_run):
    results = []
    logger.info("Scanning %d Ashby boards...", len(boards))

    for board in boards:
        jobs = ashby_client.list_jobs(board)
        if not jobs:
            continue

        matching = [j for j in jobs if matches_target_roles(j.get("text", ""), target_roles) and is_us_job(j)]
        new_matching = [j for j in matching if j["id"] not in seen_ids]

        if new_matching:
            logger.info("[%s] Found %d new matching Ashby jobs", board, len(new_matching))

        for job in new_matching:
            def submit_fn(cl, j=job):
                return browser.apply(job=j, profile=config, cover_letter=cl)

            record = _process_job(
                job["id"], job.get("text", "Unknown"), board,
                job.get("descriptionPlain", "") or job.get("description", ""),
                "ashby", scorer, config, resume_text, seen_ids, threshold, dry_run,
                submit_fn,
            )
            results.append(record)

    return results
