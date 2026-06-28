#!/usr/bin/env python3
"""Interview prep generator — triggered by 📞 reaction on a job notification.

Generates:
1. Company research summary
2. Role-specific interview questions (behavioral + technical)
3. STAR stories from your resume mapped to likely questions

Usage:
    python3 interview_prep.py <job_id>    # Generate prep for a specific job
    python3 interview_prep.py --poll      # Watch for 📞 reactions (added to reaction_poller)
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
QUALIFIED_FILE = SCRIPT_DIR / "data" / "qualified_jobs.json"
SLACK_WEBHOOK_FILE = Path.home() / ".auto-apply" / "slack_webhook"

STAR_STORIES_FILE = SCRIPT_DIR / "data" / "star_stories.txt"

PREP_PROMPT = """You are an expert interview coach. Generate interview preparation for this candidate and role.

CANDIDATE RESUME:
{resume_text}

CANDIDATE'S EXISTING STAR STORIES (from past interviews — reference and adapt these):
{star_stories}

JOB TITLE: {job_title}
COMPANY: {company}
JOB DESCRIPTION:
{job_description}

Generate the following sections:

## Company Research
- What the company does (2-3 sentences)
- Recent news/achievements if apparent from the job posting
- Company culture signals from the JD

## Likely Interview Questions

### Behavioral (5 questions)
Questions they'll probably ask based on the JD requirements. For each, reference which STAR story from the candidate's existing stories best answers it (quote the key situation).

### Technical (5 questions)
Technical questions based on the tech stack and requirements in the JD.

## STAR Stories (mapped to this role)
Pick the 4 most relevant STAR stories from the candidate's existing stories above. For each:
- Which question it answers
- The story (summarized in STAR format)
- How to tailor it specifically for THIS company/role

## Key Talking Points
3-4 bullet points that directly connect the candidate's experience to their top requirements.

Be specific to THIS role and company. Use the candidate's ACTUAL stories, not made-up ones."""


def generate_prep(job: dict) -> str:
    """Generate interview prep using kiro-cli."""
    with open(SCRIPT_DIR / "profile.yaml") as f:
        config = yaml.safe_load(f)

    from src.matcher import extract_resume_text
    resume_text = extract_resume_text(Path(config["resume_path"]).expanduser())

    # Load STAR stories
    star_stories = ""
    if STAR_STORIES_FILE.exists():
        star_stories = STAR_STORIES_FILE.read_text()[:8000]

    desc = job.get("descriptionPlain") or job.get("description", "")
    desc_clean = re.sub(r'<[^>]+>', ' ', desc)[:4000]

    prompt = PREP_PROMPT.format(
        resume_text=resume_text[:6000],
        star_stories=star_stories,
        job_title=job["text"],
        company=job.get("_company", ""),
        job_description=desc_clean,
    )

    try:
        result = subprocess.run(
            ["kiro-cli", "chat", prompt, "--legacy-ui", "--trust-tools=", "--agent", "gpu-minimal"],
            capture_output=True, text=True, timeout=180,
        )
        raw = result.stdout
        raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw).replace('\r', '\n')
        # Extract content
        lines = [l for l in raw.split('\n') if l.strip() and not any(
            k in l for k in ['Thinking', 'WARNING', 'hooks', 'Credits:', 'exit', 'changelog', 'Model:']
        )]
        return '\n'.join(lines).strip()
    except Exception as e:
        return f"Failed to generate prep: {e}"


def send_slack(msg: str) -> bool:
    webhook = SLACK_WEBHOOK_FILE.read_text().strip()
    resp = requests.post(webhook, json={"text": msg, "mrkdwn": True}, timeout=10)
    return resp.status_code == 200


def cmd_prep(job_id: str):
    """Generate and send interview prep for a job."""
    qualified = json.loads(QUALIFIED_FILE.read_text()) if QUALIFIED_FILE.exists() else []

    job = None
    for j in qualified:
        if j.get("id", "").startswith(job_id):
            job = j
            break

    if not job:
        print(f"❌ Job ID '{job_id}' not found. Run `python3 jobs.py list`")
        return

    print(f"🎓 Generating interview prep for: {job['text']} @ {job.get('_company')}")
    print("   This takes ~60 seconds...")

    prep = generate_prep(job)

    # Save to file
    out_file = SCRIPT_DIR / "data" / f"interview_prep_{job_id[:8]}.md"
    out_file.write_text(f"# Interview Prep: {job['text']} @ {job.get('_company', '')}\n\n{prep}")
    print(f"\n📄 Saved to: {out_file}")

    # Send to Slack (split if too long)
    header = f"*🎓 Interview Prep — {job['text']} @ {job.get('_company', '')}*\n\n"
    if len(prep) > 3000:
        # Split into chunks
        send_slack(header + prep[:3000] + "...")
        send_slack("..." + prep[3000:])
    else:
        send_slack(header + prep)

    print("📨 Sent to Slack!")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job_id", nargs="?", help="Job ID prefix")
    args = parser.parse_args()

    if args.job_id:
        cmd_prep(args.job_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
