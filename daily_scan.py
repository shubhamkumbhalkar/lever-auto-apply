#!/usr/bin/env python3
"""Daily job scanner — finds matching jobs, scores them, and sends links via Slack + email.

Runs daily via cron/systemd timer. Sends a digest of top matches with direct apply links.

Usage:
    python3 daily_scan.py                    # Run scan and send digest
    python3 daily_scan.py --dry-run          # Preview without sending
    python3 daily_scan.py --install-cron     # Install daily cron job at 9 AM CT
"""

import argparse
import concurrent.futures
import json
import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

from src.matcher import extract_resume_text, is_us_job, load_seen_ids, matches_target_roles, save_seen_ids

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
SLACK_WEBHOOK_FILE = Path.home() / ".auto-apply" / "slack_webhook"
MAX_WORKERS = 15


def fetch_lever(slug):
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"}, timeout=20)
        if r.status_code != 200: return []
        jobs = r.json()
        for j in jobs:
            j["_company"], j["_platform"] = slug, "lever"
            j["absolute_url"] = j.get("hostedUrl") or j.get("applyUrl") or f"https://jobs.lever.co/{slug}/{j.get('id','')}"
        return jobs
    except: return []


def fetch_greenhouse(token):
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"}, timeout=20)
        if r.status_code != 200: return []
        jobs = []
        for j in r.json().get("jobs", []):
            loc = j.get("location", {}).get("name", "") if j.get("location") else ""
            jobs.append({"id": str(j["id"]), "text": j.get("title", ""), "description": j.get("content", ""),
                         "descriptionPlain": j.get("content", ""), "categories": {"location": loc},
                         "absolute_url": j.get("absolute_url", ""), "_company": token, "_platform": "greenhouse"})
        return jobs
    except: return []


def fetch_ashby(slug):
    try:
        r = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=20)
        if r.status_code != 200: return []
        jobs = []
        for j in r.json().get("jobs", []):
            loc = j.get("location", "") or ""
            if isinstance(loc, dict): loc = loc.get("name", "")
            jobs.append({"id": j.get("id", ""), "text": j.get("title", ""), "description": j.get("descriptionHtml", ""),
                         "descriptionPlain": j.get("descriptionPlain", "") or j.get("descriptionHtml", ""),
                         "categories": {"location": loc}, "absolute_url": j.get("jobUrl", ""),
                         "_company": slug, "_platform": "ashby"})
        return jobs
    except: return []


def fetch_smartrecruiters(company):
    try:
        jobs = []
        offset = 0
        while True:
            r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                           params={"limit": 100, "offset": offset}, timeout=20)
            if r.status_code != 200: break
            data = r.json()
            for j in data.get("content", []):
                loc = j.get("location", {})
                location_str = ", ".join(filter(None, [loc.get("city", ""), loc.get("region", "")]))
                jobs.append({"id": j.get("id", ""), "text": j.get("name", ""),
                             "description": j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
                             "descriptionPlain": j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
                             "categories": {"location": location_str},
                             "absolute_url": j.get("ref", ""),
                             "_company": company, "_platform": "smartrecruiters"})
            offset += 100
            if offset >= data.get("totalFound", 0): break
        return jobs
    except: return []


def fetch_workday(board_config):
    try:
        parts = board_config.split("/", 1)
        sub_wd = parts[0]
        site = parts[1] if len(parts) > 1 else "External"
        subdomain = sub_wd.split(".")[0]
        base_url = f"https://{sub_wd}.myworkdayjobs.com/wday/cxs/{subdomain}/{site}/jobs"
        jobs = []
        offset = 0
        while offset < 500:  # Cap at 500 to avoid long fetches
            r = requests.post(base_url, json={"limit": 20, "offset": offset},
                            headers={"Content-Type": "application/json"}, timeout=20)
            if r.status_code != 200: break
            data = r.json()
            postings = data.get("jobPostings", [])
            if not postings: break
            for j in postings:
                loc = j.get("locationsText", "") or (j.get("bulletFields", [""])[0] if j.get("bulletFields") else "")
                jobs.append({"id": j.get("externalPath", f"wd_{offset}"),
                             "text": j.get("title", ""), "description": "", "descriptionPlain": "",
                             "categories": {"location": loc},
                             "absolute_url": f"https://{sub_wd}.myworkdayjobs.com{j.get('externalPath', '')}",
                             "_company": subdomain, "_platform": "workday"})
            offset += 20
            if offset >= data.get("total", 0): break
        return jobs
    except: return []


def fetch_jobspy(search_config):
    """Fetch jobs from Indeed + Google via JobSpy. search_config is a dict with location and search_term."""
    try:
        from jobspy import scrape_jobs
        location = search_config.get("location", "San Francisco, CA")
        jobs_df = scrape_jobs(
            site_name=["indeed", "google"],
            search_term="Senior Software Engineer",
            location=location,
            results_wanted=50,
            hours_old=24,
            country_indeed="USA",
        )
        jobs = []
        for _, row in jobs_df.iterrows():
            title = str(row.get("title", ""))
            company = str(row.get("company", ""))
            loc = str(row.get("location", ""))
            url = str(row.get("job_url", ""))
            desc = str(row.get("description", ""))
            job_id = str(row.get("id", "")) or f"jobspy_{hash(url) % 100000}"
            jobs.append({
                "id": job_id,
                "text": title,
                "description": desc,
                "descriptionPlain": desc,
                "categories": {"location": loc},
                "absolute_url": url,
                "_company": company,
                "_platform": "indeed/google",
            })
        return jobs
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("JobSpy fetch failed: %s", e)
        return []


def fetch_hiring_cafe(search_term="senior software engineer"):
    """Fetch jobs from Hiring.cafe (aggregates 46+ ATS platforms)."""
    try:
        import re as _re
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        slug = search_term.lower().replace(" ", "-")
        r = requests.get(f"https://hiring.cafe/jobs/{slug}", headers=headers, timeout=20)
        if r.status_code != 200: return []

        m = _re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text)
        if not m: return []
        import json as _json
        data = _json.loads(m.group(1))
        hits = data.get("props", {}).get("pageProps", {}).get("ssrHits", [])

        jobs = []
        for h in hits:
            if h.get("source") == "hiring_cafe_pin": continue  # Skip their own ads
            v5 = h.get("v5_processed_job_data", {})
            company_data = h.get("enriched_company_data", {})
            title = h.get("job_title") or h.get("job_information", {}).get("title", "")
            company = company_data.get("name", "")
            location = v5.get("formatted_workplace_location", "")
            url = h.get("hc_apply_url") or ""
            desc = v5.get("requirements_summary", "") or h.get("job_information", {}).get("description", "")
            job_id = h.get("id") or h.get("objectID", "")

            if not title or not company: continue
            jobs.append({
                "id": job_id,
                "text": title,
                "description": desc,
                "descriptionPlain": desc,
                "categories": {"location": location},
                "absolute_url": url,
                "_company": company,
                "_platform": "hiring.cafe",
            })
        return jobs
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Hiring.cafe fetch failed: %s", e)
        return []


def fetch_yc_jobs():
    """Fetch jobs from Y Combinator's Work at a Startup."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://www.workatastartup.com/api/companies/search", params={
            "query": "software engineer",
            "demographic": "senior",
            "page": 1,
        }, headers=headers, timeout=20)
        if r.status_code != 200: return []
        data = r.json()
        jobs = []
        for company in data.get("companies", data) if isinstance(data, dict) else []:
            for job in company.get("jobs", []):
                jobs.append({
                    "id": str(job.get("id", "")),
                    "text": job.get("title", ""),
                    "description": job.get("description", ""),
                    "descriptionPlain": job.get("description", ""),
                    "categories": {"location": job.get("location", "")},
                    "absolute_url": f"https://www.workatastartup.com/jobs/{job.get('id','')}",
                    "_company": company.get("name", ""),
                    "_platform": "yc",
                })
        return jobs
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("YC jobs fetch failed: %s", e)
        return []

def scan_all(companies, target_roles, seen_ids):
    """Fetch all boards in parallel, return new matching jobs."""
    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for slug in companies.get("lever", []):
            tasks.append(ex.submit(fetch_lever, slug))
        for token in companies.get("greenhouse", []):
            tasks.append(ex.submit(fetch_greenhouse, token))
        for slug in companies.get("ashby", []):
            tasks.append(ex.submit(fetch_ashby, slug))
        for company in companies.get("smartrecruiters", []):
            tasks.append(ex.submit(fetch_smartrecruiters, company))
        for board_config in companies.get("workday", []):
            tasks.append(ex.submit(fetch_workday, board_config))
        # JobSpy: Indeed + Google Jobs for SF and Seattle
        for loc in ["San Francisco, CA", "Seattle, WA"]:
            tasks.append(ex.submit(fetch_jobspy, {"location": loc}))
        # Hiring.cafe: aggregates 46+ ATS platforms
        tasks.append(ex.submit(fetch_hiring_cafe, "senior software engineer"))
        tasks.append(ex.submit(fetch_hiring_cafe, "senior backend engineer"))
        # YC Work at a Startup
        tasks.append(ex.submit(fetch_yc_jobs))

        all_jobs = []
        for f in concurrent.futures.as_completed(tasks):
            all_jobs.extend(f.result())

    matching = [j for j in all_jobs if matches_target_roles(j.get("text", ""), target_roles) and is_us_job(j)]
    new_matching = [j for j in matching if j["id"] not in seen_ids]

    # Deduplicate by title+company before scoring (keep first seen)
    unique = {}
    for j in new_matching:
        key = (j.get("text", "").strip(), j.get("_company", ""))
        if key not in unique:
            unique[key] = j
    return list(unique.values())


def score_jobs(jobs, resume_text, threshold=75, max_to_score=100):
    """Score top jobs using local kiro-cli scorer. Returns sorted list."""
    from src.scorer import create_scorer
    scorer = create_scorer(backend="local")

    all_candidates = jobs

    # Ensure diversity: max 2 jobs per company, and include jobs from all platforms
    from collections import Counter
    company_count = Counter()
    to_score = []
    # First pass: ensure each platform gets at least 5 slots
    platform_jobs = {}
    for j in all_candidates:
        platform_jobs.setdefault(j.get("_platform", ""), []).append(j)

    for platform, pjobs in platform_jobs.items():
        added = 0
        for j in pjobs:
            if added >= 5 or len(to_score) >= max_to_score:
                break
            company = j.get("_company", "")
            if company_count[company] < 2:
                to_score.append(j)
                company_count[company] += 1
                added += 1

    # Second pass: fill up to max with remaining, respecting company cap
    for j in all_candidates:
        if len(to_score) >= max_to_score:
            break
        if j in to_score:
            continue
        company = j.get("_company", "")
        if company_count[company] < 2:
            to_score.append(j)
            company_count[company] += 1

    results = []
    for j in to_score:
        desc = j.get("descriptionPlain") or j.get("description", "")
        score_result = scorer.score_ats(resume_text, desc)
        j["_score"] = score_result.get("score", 0)
        j["_reasoning"] = score_result.get("reasoning", "")
        results.append(j)

    results.sort(key=lambda x: -x["_score"])
    return results


def build_digest(scored_jobs, threshold=75):
    """Build a formatted digest message."""
    above = [j for j in scored_jobs if j["_score"] >= threshold]
    below = [j for j in scored_jobs if j["_score"] < threshold and j["_score"] >= 60]

    lines = []
    lines.append(f"🎯 *Job Scan Results — {datetime.now().strftime('%B %d, %Y')}*\n")

    if above:
        lines.append(f"*✅ {len(above)} jobs above threshold ({threshold}+):*\n")
        for j in above:
            url = j.get("absolute_url") or j.get("hostedUrl") or f"https://jobs.lever.co/{j.get("_company","")}/{j.get("id","")}"
            lines.append(f"• *{j['_score']}* — {j['text']}")
            lines.append(f"  @ {j['_company']} ({j['_platform']}) — {j.get('categories', {}).get('location', '?')}")
            lines.append(f"  → <{url}|Apply Here>")
            lines.append("")

    if below:
        lines.append(f"\n*🟡 {len(below)} near-threshold (60-74):*\n")
        for j in below[:10]:
            url = j.get("absolute_url") or j.get("hostedUrl") or f"https://jobs.lever.co/{j.get("_company","")}/{j.get("id","")}"
            lines.append(f"• *{j['_score']}* — {j['text']} @ {j['_company']} → <{url}|Apply>")

    if not above and not below:
        lines.append("No new matching jobs found today. Will check again tomorrow!")

    return "\n".join(lines)


def build_email_html(scored_jobs, threshold=75):
    """Build HTML email version."""
    above = [j for j in scored_jobs if j["_score"] >= threshold]
    below = [j for j in scored_jobs if j["_score"] < threshold and j["_score"] >= 60]

    html = [f"<h2>🎯 Job Scan Results — {datetime.now().strftime('%B %d, %Y')}</h2>"]

    if above:
        html.append(f"<h3>✅ {len(above)} jobs above threshold ({threshold}+):</h3><ul>")
        for j in above:
            url = j.get("absolute_url") or j.get("hostedUrl") or f"https://jobs.lever.co/{j.get("_company","")}/{j.get("id","")}"
            loc = j.get("categories", {}).get("location", "?")
            html.append(f'<li><strong>{j["_score"]}</strong> — {j["text"]}<br/>')
            html.append(f'@ {j["_company"]} ({j["_platform"]}) — {loc}<br/>')
            html.append(f'<a href="{url}">👉 Apply Here</a></li><br/>')
        html.append("</ul>")

    if below:
        html.append(f"<h3>🟡 {len(below)} near-threshold (60-74):</h3><ul>")
        for j in below[:10]:
            url = j.get("absolute_url") or j.get("hostedUrl") or f"https://jobs.lever.co/{j.get("_company","")}/{j.get("id","")}"
            html.append(f'<li><strong>{j["_score"]}</strong> — {j["text"]} @ {j["_company"]} — <a href="{url}">Apply</a></li>')
        html.append("</ul>")

    if not above and not below:
        html.append("<p>No new matching jobs found today.</p>")

    return "\n".join(html)


def send_slack(message):
    """Send digest via Slack webhook."""
    if not SLACK_WEBHOOK_FILE.exists():
        logger.warning("No Slack webhook configured at %s", SLACK_WEBHOOK_FILE)
        return False
    webhook_url = SLACK_WEBHOOK_FILE.read_text().strip()
    try:
        resp = requests.post(webhook_url, json={"text": message, "mrkdwn": True}, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error("Slack send failed: %s", e)
        return False


def send_email(html_body, to_email):
    """Send digest via sendmail."""
    msg = f"""From: Job Scanner <noreply@auto-apply>
To: {to_email}
Subject: 🎯 Daily Job Matches — {datetime.now().strftime('%b %d')}
MIME-Version: 1.0
Content-Type: text/html; charset=utf-8

{html_body}"""

    try:
        proc = subprocess.run(["sendmail", to_email], input=msg, capture_output=True, text=True, timeout=10)
        return proc.returncode == 0
    except Exception as e:
        logger.error("Email send failed: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    parser.add_argument("--no-score", action="store_true", help="Skip ATS scoring (faster)")
    parser.add_argument("--install-cron", action="store_true", help="Install daily cron at 9 AM CT")
    args = parser.parse_args()

    if args.install_cron:
        script_path = Path(__file__).resolve()
        cron_line = f"0 14 * * * cd {SCRIPT_DIR} && python3 {script_path} >> /tmp/daily_scan.log 2>&1"
        # 14:00 UTC = 9:00 AM CT
        os.system(f'(crontab -l 2>/dev/null | grep -v "daily_scan.py"; echo "{cron_line}") | crontab -')
        print(f"✅ Cron installed: runs daily at 9 AM CT (14:00 UTC)")
        print(f"   Logs: /tmp/daily_scan.log")
        return

    os.chdir(SCRIPT_DIR)

    with open("profile.yaml") as f:
        config = yaml.safe_load(f)
    with open("companies.yaml") as f:
        companies = yaml.safe_load(f)

    target_roles = config.get("target_roles", [])
    threshold = config.get("ats_threshold", 75)
    seen_ids = load_seen_ids()

    # Scan
    logger.info("Scanning all platforms...")
    t0 = time.time()
    new_jobs = scan_all(companies, target_roles, seen_ids)
    logger.info("Found %d new matching jobs in %.1fs", len(new_jobs), time.time() - t0)

    if not new_jobs:
        msg = f"🎯 Daily scan ({datetime.now().strftime('%b %d')}): No new jobs found."
        if not args.dry_run:
            send_slack(msg)
        else:
            print(msg)
        return

    # Score (optional)
    if not args.no_score:
        # Check Midway cookie freshness
        midway_cookie = Path.home() / ".midway" / "cookie"
        if midway_cookie.exists() and (time.time() - midway_cookie.stat().st_mtime) > 72000:
            logger.warning("Midway cookie is stale (>20h). Sending links without scores.")
            send_slack("⚠️ Midway expired — today's job digest is unscored. Run `mwinit` for scored results tomorrow.")
            args.no_score = True
        else:
            resume_text = extract_resume_text(Path(config["resume_path"]).expanduser())
            logger.info("Scoring top %d jobs...", min(100, len(new_jobs)))
            try:
                scored = score_jobs(new_jobs, resume_text, threshold)
            except Exception as e:
                logger.error("Scoring failed: %s. Sending unscored.", e)
                send_slack(f"⚠️ Scoring failed ({e}). Sending unscored links.")
                args.no_score = True

    if args.no_score:
        # Just sort by seniority preference
        scored = sorted(new_jobs, key=lambda j: j.get("text", ""))
        for j in scored:
            j["_score"] = 0

    # Mark as seen
    for j in scored:
        seen_ids.add(j["id"])
    save_seen_ids(seen_ids)

    # Deduplicate by title + company (keep highest score)
    seen_titles = {}
    for j in scored:
        key = (j.get("text", "").strip(), j.get("_company", ""))
        if key not in seen_titles or j.get("_score", 0) > seen_titles[key].get("_score", 0):
            seen_titles[key] = j
    scored = sorted(seen_titles.values(), key=lambda x: -x.get("_score", 0))

    # Build and send
    effective_threshold = threshold if not args.no_score else 0
    slack_msg = build_digest(scored, effective_threshold)
    email_html = build_email_html(scored, effective_threshold)

    if args.dry_run:
        print(slack_msg)
        return

    # Send via both channels
    if send_slack(slack_msg):
        logger.info("✅ Slack digest sent")
    else:
        logger.warning("❌ Slack failed")

    # Save qualified jobs and send individual notifications with cover letters
    # Only send individual notifications when ATS scoring actually ran (not stale midway fallback)
    above = [j for j in scored if j.get("_score", 0) >= effective_threshold]
    if above and not args.no_score:
        from jobs import save_qualified, load_qualified, load_applied, send_job_notification
        existing = load_qualified()
        existing_ids = {j.get("id") for j in existing}
        new_qualified = [j for j in above if j.get("id") not in existing_ids]
        if new_qualified:
            save_qualified(existing + new_qualified)
            applied = load_applied()
            # Get scorer + resume for cover letter generation
            if 'resume_text' in dir():
                from src.scorer import create_scorer as _cs
                notif_scorer = _cs(backend="local")
            else:
                resume_text = ""
                notif_scorer = None
            sent = 0
            for j in new_qualified:
                if j.get("id", "") not in applied:
                    send_job_notification(j, resume_text=resume_text, scorer=notif_scorer)
                    sent += 1
                    time.sleep(2)
            logger.info("📬 Sent %d individual job notifications with cover letters", sent)

    logger.info("Done! %d jobs scored, %d above threshold.", len(scored), sum(1 for j in scored if j["_score"] >= threshold))


if __name__ == "__main__":
    main()


