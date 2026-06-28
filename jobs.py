#!/usr/bin/env python3
"""Job management CLI — per-job Slack notifications, cover letters, and tracking.

Usage:
    python3 jobs.py notify          # Send individual Slack msg per qualified job (used by daily cron)
    python3 jobs.py cover <job_id>  # Generate cover letter for a specific job
    python3 jobs.py applied <job_id> # Mark a job as applied
    python3 jobs.py list            # Show today's qualified jobs
    python3 jobs.py status          # Show applied/pending stats
"""

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

from src.matcher import extract_resume_text, is_us_job, matches_target_roles
from src.scorer import create_scorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
QUALIFIED_FILE = SCRIPT_DIR / "data" / "qualified_jobs.json"
APPLIED_FILE = SCRIPT_DIR / "data" / "applied_jobs.json"
SLACK_WEBHOOK_FILE = Path.home() / ".auto-apply" / "slack_webhook"


def load_qualified() -> list[dict]:
    if QUALIFIED_FILE.exists():
        return json.loads(QUALIFIED_FILE.read_text())
    return []


def save_qualified(jobs: list[dict]):
    QUALIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUALIFIED_FILE.write_text(json.dumps(jobs, indent=2, default=str))


def load_applied() -> dict:
    """Returns {job_id: {job_data + applied_at}}"""
    if APPLIED_FILE.exists():
        return json.loads(APPLIED_FILE.read_text())
    return {}


def save_applied(data: dict):
    APPLIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPLIED_FILE.write_text(json.dumps(data, indent=2, default=str))


def send_slack(message: str) -> bool:
    if not SLACK_WEBHOOK_FILE.exists():
        return False
    webhook = SLACK_WEBHOOK_FILE.read_text().strip()
    try:
        resp = requests.post(webhook, json={"text": message, "mrkdwn": True}, timeout=10)
        return resp.status_code == 200
    except:
        return False


def send_job_notification(job: dict, resume_text: str = "", scorer=None) -> bool:
    """Send a single Slack message for one job, including a generated cover letter."""
    url = job.get("absolute_url") or job.get("hostedUrl") or ""
    loc = job.get("categories", {}).get("location", "?")
    score = job.get("_score", 0)
    job_id = job.get("id", "?")[:8]
    reasoning = job.get("_reasoning", "")

    # Generate cover letter + "why this company"
    cover_letter = ""
    why_company = ""
    if resume_text and scorer:
        desc = job.get("descriptionPlain") or job.get("description", "")
        import re
        desc_clean = re.sub(r'<[^>]+>', ' ', desc)
        if desc_clean.strip():
            cover_letter = scorer.generate_cover_letter(
                resume_text, job["text"], job.get("_company", ""), desc_clean
            )
            # Generate "why this company" answer
            why_prompt = (
                f"You are a job applicant. In 2-3 sentences, answer: 'Why do you want to work at {job.get('_company', '')}?'\n"
                f"Base your answer on this job description and the candidate's background.\n"
                f"Be specific to THIS company — mention their product, mission, or tech.\n"
                f"Keep it genuine and concise.\n\n"
                f"Job: {job['text']} at {job.get('_company', '')}\n"
                f"Description excerpt: {desc_clean[:1500]}\n\n"
                f"Candidate background: 9 years SWE, Amazon (high-scale backend, microservices), "
                f"LendingClub (fintech), Java/Python/AWS/distributed systems.\n\n"
                f"Answer:"
            )
            import subprocess
            try:
                result = subprocess.run(
                    ["kiro-cli", "chat", why_prompt, "--legacy-ui", "--trust-tools=", "--agent", "gpu-minimal"],
                    capture_output=True, text=True, timeout=60,
                )
                raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', result.stdout).replace('\r', '\n')
                # Extract meaningful text
                lines = [l.strip() for l in raw.split('\n') if l.strip() and not any(
                    k in l for k in ['Thinking', 'WARNING', 'hooks', 'Credits:', 'exit', 'changelog', 'Model:']
                )]
                why_company = ' '.join(lines[-3:]).strip()
            except:
                pass

    msg = (
        f"*🎯 New Match — Score: {score}*\n\n"
        f"*{job['text']}*\n"
        f"🏢 _{job.get('_company', '?')}_ ({job.get('_platform', '?')})\n"
        f"📍 {loc}\n\n"
        f"💡 _{reasoning[:150]}{'...' if len(reasoning) > 150 else ''}_\n\n"
        f"<{url}|👉 Apply Here>\n"
    )

    if cover_letter:
        msg += f"\n*📝 Cover Letter:*\n```\n{cover_letter}\n```\n"

    if why_company:
        msg += f"\n*❓ Why {job.get('_company', 'this company')}?*\n_{why_company}_\n"

    msg += (
        f"\n───────────────\n"
        f"`jobs.py applied {job_id}` → mark as applied ✅"
    )
    return send_slack(msg)


def cmd_notify(args):
    """Send individual Slack notifications for today's qualified jobs."""
    qualified = load_qualified()
    applied = load_applied()

    # Only notify for jobs not already applied to
    pending = [j for j in qualified if j.get("id", "") not in applied]

    if not pending:
        logger.info("No pending qualified jobs to notify about.")
        return

    sent = 0
    for j in pending:
        if send_job_notification(j):
            sent += 1
            time.sleep(1)  # Rate limit Slack

    logger.info("Sent %d individual job notifications to Slack.", sent)


def cmd_cover(args):
    """Generate a cover letter for a specific job."""
    job_id = args.job_id
    qualified = load_qualified()

    # Find job by ID prefix match
    job = None
    for j in qualified:
        if j.get("id", "").startswith(job_id):
            job = j
            break

    if not job:
        print(f"❌ Job ID '{job_id}' not found in qualified jobs.")
        print(f"   Run `python3 jobs.py list` to see available jobs.")
        return

    print(f"Generating cover letter for: {job['text']} @ {job.get('_company', '?')}")
    print("=" * 60)

    with open(SCRIPT_DIR / "profile.yaml") as f:
        config = yaml.safe_load(f)

    resume_text = extract_resume_text(Path(config["resume_path"]).expanduser())
    scorer = create_scorer(backend="local")

    desc = job.get("descriptionPlain") or job.get("description", "")
    desc_clean = re.sub(r'<[^>]+>', ' ', desc)

    cover_letter = scorer.generate_cover_letter(
        resume_text, job["text"], job.get("_company", ""), desc_clean
    )

    print(cover_letter)
    print("=" * 60)

    # Also save to file for easy copy
    out_file = Path(f"/tmp/cover_letter_{job_id[:8]}.txt")
    out_file.write_text(cover_letter)
    print(f"\n📄 Saved to: {out_file}")

    # Send to Slack too
    slack_msg = (
        f"*📝 Cover Letter — {job['text']} @ {job.get('_company', '')}*\n\n"
        f"```\n{cover_letter}\n```"
    )
    if send_slack(slack_msg):
        print("📨 Also sent to Slack!")


def cmd_applied(args):
    """Mark a job as applied."""
    job_id = args.job_id
    qualified = load_qualified()
    applied = load_applied()

    job = None
    for j in qualified:
        if j.get("id", "").startswith(job_id):
            job = j
            break

    if not job:
        print(f"❌ Job ID '{job_id}' not found.")
        return

    applied[job["id"]] = {
        "title": job["text"],
        "company": job.get("_company", ""),
        "score": job.get("_score", 0),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "url": job.get("absolute_url", ""),
    }
    save_applied(applied)

    print(f"✅ Marked as applied: {job['text']} @ {job.get('_company', '')}")

    # Notify Slack
    send_slack(f"✅ Applied: *{job['text']}* @ _{job.get('_company', '')}_  (Score: {job.get('_score', 0)})")


def cmd_list(args):
    """List current qualified jobs."""
    qualified = load_qualified()
    applied = load_applied()

    if not qualified:
        print("No qualified jobs. Run the daily scan first.")
        return

    print(f"\n{'Score':>5}  {'Status':>8}  {'Title':<50}  {'Company':<15}  ID")
    print("-" * 100)
    for j in sorted(qualified, key=lambda x: -x.get("_score", 0)):
        status = "✅" if j.get("id", "") in applied else "⏳"
        title = j["text"][:48]
        company = j.get("_company", "?")[:13]
        jid = j.get("id", "?")[:8]
        print(f"{j.get('_score', 0):>5}  {status:>8}  {title:<50}  {company:<15}  {jid}")


def cmd_status(args):
    """Show application stats."""
    qualified = load_qualified()
    applied = load_applied()

    total = len(qualified)
    applied_count = sum(1 for j in qualified if j.get("id", "") in applied)
    pending = total - applied_count

    print(f"\n📊 Application Status")
    print(f"   Total qualified: {total}")
    print(f"   ✅ Applied: {applied_count}")
    print(f"   ⏳ Pending: {pending}")
    print(f"\n   Total applied (all time): {len(applied)}")


def main():
    parser = argparse.ArgumentParser(description="Job management CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("notify", help="Send individual Slack notifications")
    p_cover = sub.add_parser("cover", help="Generate cover letter for a job")
    p_cover.add_argument("job_id", help="Job ID (or prefix)")
    p_applied = sub.add_parser("applied", help="Mark job as applied")
    p_applied.add_argument("job_id", help="Job ID (or prefix)")
    sub.add_parser("list", help="List qualified jobs")
    sub.add_parser("status", help="Show stats")

    args = parser.parse_args()

    if args.command == "notify": cmd_notify(args)
    elif args.command == "cover": cmd_cover(args)
    elif args.command == "applied": cmd_applied(args)
    elif args.command == "list": cmd_list(args)
    elif args.command == "status": cmd_status(args)
    else: parser.print_help()


if __name__ == "__main__":
    main()
