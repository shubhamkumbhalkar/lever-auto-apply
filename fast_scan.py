#!/usr/bin/env python3
"""Fast parallel job scanner — fetches all boards concurrently.

Usage:
    python3 fast_scan.py --profile profile.yaml                    # Scan all, show matches
    python3 fast_scan.py --profile profile.yaml --platform lever   # Lever only
    python3 fast_scan.py --profile profile.yaml --score            # Also ATS-score matches
    python3 fast_scan.py --profile profile.yaml --apply            # Score + apply (not dry-run)
"""

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from pathlib import Path

import requests
import yaml

from src.matcher import extract_resume_text, is_us_job, load_seen_ids, matches_target_roles, save_seen_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

MAX_WORKERS = 15  # concurrent HTTP fetches


def fetch_lever(slug: str) -> list[dict]:
    try:
        resp = requests.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=20)
        if resp.status_code != 200:
            return []
        jobs = resp.json()
        for j in jobs:
            j["_company"] = slug
            j["_platform"] = "lever"
        return jobs
    except Exception:
        return []


def fetch_greenhouse(token: str) -> list[dict]:
    try:
        resp = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                           params={"content": "true"}, timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for j in data.get("jobs", []):
            location = j.get("location", {}).get("name", "") if j.get("location") else ""
            jobs.append({
                "id": str(j["id"]),
                "text": j.get("title", ""),
                "description": j.get("content", ""),
                "descriptionPlain": j.get("content", ""),
                "categories": {"location": location},
                "absolute_url": j.get("absolute_url", ""),
                "_company": token,
                "_platform": "greenhouse",
            })
        return jobs
    except Exception:
        return []


def fetch_ashby(slug: str) -> list[dict]:
    try:
        resp = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
        jobs = []
        for j in data.get("jobs", []):
            location = j.get("location", "") or ""
            if isinstance(location, dict):
                location = location.get("name", "")
            jobs.append({
                "id": j.get("id", ""),
                "text": j.get("title", ""),
                "description": j.get("descriptionHtml", ""),
                "descriptionPlain": j.get("descriptionPlain", "") or j.get("descriptionHtml", ""),
                "categories": {"location": location},
                "absolute_url": j.get("jobUrl", ""),
                "_company": slug,
                "_platform": "ashby",
            })
        return jobs
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="Fast parallel job scanner")
    parser.add_argument("--profile", "-p", required=True)
    parser.add_argument("--platform", choices=["all", "lever", "greenhouse", "ashby"], default="all")
    parser.add_argument("--score", action="store_true", help="ATS-score matching jobs")
    parser.add_argument("--apply", action="store_true", help="Score and apply")
    parser.add_argument("--companies", default="companies.yaml")
    args = parser.parse_args()

    with open(args.profile) as f:
        config = yaml.safe_load(f)
    with open(args.companies) as f:
        companies = yaml.safe_load(f)

    target_roles = config.get("target_roles", [])
    seen_ids = load_seen_ids()

    # Phase 1: Fetch all boards in parallel
    all_jobs = []
    tasks = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        if args.platform in ("lever", "all"):
            for slug in companies.get("lever", []):
                tasks.append(ex.submit(fetch_lever, slug))
        if args.platform in ("greenhouse", "all"):
            for token in companies.get("greenhouse", []):
                tasks.append(ex.submit(fetch_greenhouse, token))
        if args.platform in ("ashby", "all"):
            for slug in companies.get("ashby", []):
                tasks.append(ex.submit(fetch_ashby, slug))

        logger.info("Fetching %d boards in parallel...", len(tasks))
        t0 = time.time()
        for f in concurrent.futures.as_completed(tasks):
            all_jobs.extend(f.result())

    elapsed = time.time() - t0
    logger.info("Fetched %d total postings in %.1fs", len(all_jobs), elapsed)

    # Phase 2: Filter
    matching = [j for j in all_jobs if matches_target_roles(j.get("text", ""), target_roles) and is_us_job(j)]
    new_matching = [j for j in matching if j["id"] not in seen_ids]

    logger.info("Matching: %d total, %d new (unseen)", len(matching), len(new_matching))

    if not new_matching:
        logger.info("No new matches found.")
        return

    # Print matches
    print(f"\n{'='*80}")
    print(f"  {len(new_matching)} NEW MATCHING JOBS")
    print(f"{'='*80}\n")
    for i, j in enumerate(new_matching, 1):
        loc = j.get("categories", {}).get("location", "?")
        print(f"  {i:3}. {j['text']}")
        print(f"       @ {j['_company']} ({j['_platform']}) — {loc}")
        if j.get("absolute_url"):
            print(f"       {j['absolute_url']}")
        print()

    # Phase 3: Score (optional)
    if args.score or args.apply:
        from src.scorer import create_scorer
        resume_path = Path(config["resume_path"]).expanduser()
        resume_text = extract_resume_text(resume_path)
        scorer = create_scorer(backend="local")
        threshold = config.get("ats_threshold", 75)

        print(f"\n{'='*80}")
        print(f"  SCORING {len(new_matching)} JOBS (threshold: {threshold})")
        print(f"{'='*80}\n")

        qualified = []
        for j in new_matching:
            desc = j.get("descriptionPlain") or j.get("description", "")
            result = scorer.score_ats(resume_text, desc)
            score = result.get("score", 0)
            j["_score"] = score
            j["_reasoning"] = result.get("reasoning", "")
            status = "✅" if score >= threshold else "❌"
            print(f"  {status} {score:3d} — {j['text']} @ {j['_company']}")
            if score >= threshold:
                qualified.append(j)
            seen_ids.add(j["id"])

        save_seen_ids(seen_ids)
        print(f"\n  {len(qualified)}/{len(new_matching)} jobs above threshold")

        if args.apply and qualified:
            logger.info("Applying to %d qualified jobs...", len(qualified))
            # Import and run the normal pipeline's apply logic
            from src.pipeline import run_pipeline
            run_pipeline(args.profile, dry_run=False, platform=args.platform)
    else:
        # Just mark as seen so next run shows only new
        # (Don't mark — let the user decide)
        print("  💡 Run with --score to ATS-score these, or --apply to auto-apply")


if __name__ == "__main__":
    main()
