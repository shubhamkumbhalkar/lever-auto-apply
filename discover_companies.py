#!/usr/bin/env python3
"""Discover new tech companies on Lever & Greenhouse and validate existing ones.

Usage:
    python3 discover_companies.py              # Discover + validate, update companies.yaml
    python3 discover_companies.py --validate   # Only validate existing (remove dead boards)
    python3 discover_companies.py --discover   # Only discover new companies
"""

import argparse
import concurrent.futures
import logging
import time

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

COMPANIES_FILE = "companies.yaml"

# Known tech companies to try on Lever (curated from YC, top startups, etc.)
# These are slugs that appear in jobs.lever.co/{slug}
LEVER_CANDIDATES = [
    # Large/well-known tech
    "twitch", "snap", "notion", "figma", "canva", "datadog", "hashicorp",
    "confluent", "elastic-co", "gitlab", "mongodb", "pagerduty",
    "snowflake", "splunk", "zoominfo", "hubspot", "atlassian",
    "ramp", "brex", "rippling", "gusto", "deel", "remote-com",
    # AI/ML
    "anthropic", "openai", "cohere", "stability-ai", "huggingface",
    "replit", "jasper-ai", "midjourney", "runway", "scale-ai",
    "weights-and-biases", "labelbox", "snorkel-ai", "mosaic-ml",
    "inflection-ai", "adept-ai", "character-ai",
    # Fintech
    "chime", "mercury", "ramp", "brex", "plaid", "stripe-2",
    "affirm", "marqeta", "lithic", "pipe", "rho", "treasury-prime",
    # Infrastructure / DevTools
    "vercel", "supabase", "planetscale", "neon-inc", "railway",
    "fly-io", "render", "dagger-io", "pulumi", "env0",
    "snyk", "lacework", "orca-security", "wiz-io",
    # Crypto/Web3
    "alchemy", "chainalysis", "fireblocks", "consensys", "dydx",
    "uniswap-labs", "aave", "polygon-technology", "aptos-labs",
    # Health/Bio
    "tempus", "flatiron", "veracyte", "recursion", "insitro",
    # Unicorns / Growth
    "notion", "airtable-2", "calendly", "loom", "miro",
    "clickup", "linear", "retool", "webflow", "zapier",
    "grafana-labs", "postman", "Kong", "temporal-technologies",
]

# Known Greenhouse board tokens to try
GREENHOUSE_CANDIDATES = [
    # Large tech
    "snap", "notion", "canva", "datadog", "hashicorp",
    "confluent", "mongodb", "pagerduty", "snowflakecomputing",
    "hubspot", "atlassian", "twilio", "block",
    # AI/ML
    "anthropic", "openai", "cohere", "stabilityai", "huggingface",
    "replit", "scaleai", "wandb",
    # Fintech
    "chime", "mercury", "affirm", "marqeta",
    # Infrastructure
    "vercel", "supabase", "snyk",
    # Unicorns
    "notion", "retool", "webflow", "zapier", "grafaboratories",
    "temporal", "linear",
    # Additional well-known
    "meta", "apple", "google", "microsoft", "nvidia",
    "palantir", "salesforce", "servicenow", "workday",
    "crowdstrike", "fortinet", "zscaler",
    "doordash", "uber", "lyft", "instacart",
    "roblox", "epicgames", "unity",
]

TARGET_ROLES = ["software engineer", "software development engineer", "backend engineer",
                "full stack engineer", "platform engineer"]


def check_lever(slug: str, timeout: int = 15) -> dict | None:
    """Check if a Lever slug is valid and has relevant jobs."""
    try:
        resp = requests.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        jobs = resp.json()
        if not jobs:
            return None
        # Check if any match our target roles
        relevant = [j for j in jobs if any(r in j.get("text", "").lower() for r in TARGET_ROLES)]
        if relevant:
            return {"slug": slug, "total_jobs": len(jobs), "relevant": len(relevant)}
        return None
    except Exception:
        return None


def check_greenhouse(token: str, timeout: int = 15) -> dict | None:
    """Check if a Greenhouse board token is valid and has relevant jobs."""
    try:
        resp = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
        if not jobs:
            return None
        relevant = [j for j in jobs if any(r in j.get("title", "").lower() for r in TARGET_ROLES)]
        if relevant:
            return {"token": token, "total_jobs": len(jobs), "relevant": len(relevant)}
        return None
    except Exception:
        return None


def validate_existing(companies: dict) -> dict:
    """Remove dead boards from existing companies list."""
    valid = {"lever": [], "greenhouse": []}

    logger.info("Validating %d Lever companies...", len(companies.get("lever", [])))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_lever, slug): slug for slug in companies.get("lever", [])}
        for f in concurrent.futures.as_completed(futures):
            slug = futures[f]
            result = f.result()
            if result:
                valid["lever"].append(slug)
            else:
                logger.info("  Removing dead Lever board: %s", slug)

    logger.info("Validating %d Greenhouse boards...", len(companies.get("greenhouse", [])))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_greenhouse, token): token for token in companies.get("greenhouse", [])}
        for f in concurrent.futures.as_completed(futures):
            token = futures[f]
            result = f.result()
            if result:
                valid["greenhouse"].append(token)
            else:
                logger.info("  Removing dead Greenhouse board: %s", token)

    logger.info("Validation complete: %d/%d Lever, %d/%d Greenhouse still active",
                len(valid["lever"]), len(companies.get("lever", [])),
                len(valid["greenhouse"]), len(companies.get("greenhouse", [])))
    return valid


def discover_new(existing: dict) -> dict:
    """Find new companies not already in the list."""
    existing_lever = set(existing.get("lever", []))
    existing_gh = set(existing.get("greenhouse", []))

    new_lever_candidates = [s for s in LEVER_CANDIDATES if s not in existing_lever]
    new_gh_candidates = [t for t in GREENHOUSE_CANDIDATES if t not in existing_gh]

    found = {"lever": [], "greenhouse": []}

    logger.info("Checking %d new Lever candidates...", len(new_lever_candidates))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_lever, slug): slug for slug in new_lever_candidates}
        for f in concurrent.futures.as_completed(futures):
            slug = futures[f]
            result = f.result()
            if result:
                found["lever"].append(slug)
                logger.info("  ✅ NEW Lever: %s (%d relevant jobs)", slug, result["relevant"])

    logger.info("Checking %d new Greenhouse candidates...", len(new_gh_candidates))
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(check_greenhouse, token): token for token in new_gh_candidates}
        for f in concurrent.futures.as_completed(futures):
            token = futures[f]
            result = f.result()
            if result:
                found["greenhouse"].append(token)
                logger.info("  ✅ NEW Greenhouse: %s (%d relevant jobs)", token, result["relevant"])

    logger.info("Discovery complete: found %d new Lever, %d new Greenhouse",
                len(found["lever"]), len(found["greenhouse"]))
    return found


def main():
    parser = argparse.ArgumentParser(description="Discover and validate company job boards")
    parser.add_argument("--validate", action="store_true", help="Only validate existing companies")
    parser.add_argument("--discover", action="store_true", help="Only discover new companies")
    args = parser.parse_args()

    with open(COMPANIES_FILE) as f:
        companies = yaml.safe_load(f)

    if not args.discover:
        companies = validate_existing(companies)

    if not args.validate:
        new = discover_new(companies)
        companies["lever"] = sorted(set(companies.get("lever", []) + new["lever"]))
        companies["greenhouse"] = sorted(set(companies.get("greenhouse", []) + new["greenhouse"]))

    # Write updated list
    with open(COMPANIES_FILE, "w") as f:
        f.write("# Companies to monitor — organized by job portal platform\n")
        f.write("# Auto-updated by discover_companies.py\n\n")
        yaml.dump(companies, f, default_flow_style=False, sort_keys=False)

    logger.info("Updated %s: %d Lever + %d Greenhouse = %d total",
                COMPANIES_FILE, len(companies["lever"]), len(companies["greenhouse"]),
                len(companies["lever"]) + len(companies["greenhouse"]))


if __name__ == "__main__":
    main()
