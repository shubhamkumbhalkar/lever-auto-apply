#!/usr/bin/env python3
"""Slack reaction poller — watches for ✅ reactions on job notifications and marks them as applied.

Runs as a background daemon. Polls every 60 seconds.

Usage:
    python3 reaction_poller.py          # Run in foreground
    python3 reaction_poller.py --daemon  # Run in background
"""

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
TOKEN_FILE = Path.home() / ".auto-apply" / "slack_bot_token"
CHANNEL_ID = os.environ.get("SLACK_CHANNEL_ID", "")
POLL_INTERVAL = 60  # seconds
LAST_CHECK_FILE = SCRIPT_DIR / "data" / "last_reaction_check.txt"
APPLIED_REACTIONS = {"white_check_mark", "heavy_check_mark", "ballot_box_with_check"}


def get_token():
    return TOKEN_FILE.read_text().strip()


def poll_reactions():
    """Check recent messages for ✅ reactions and mark jobs as applied."""
    from jobs import load_qualified, load_applied, save_applied

    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Get last check timestamp
    oldest = "0"
    if LAST_CHECK_FILE.exists():
        oldest = LAST_CHECK_FILE.read_text().strip()

    # Fetch recent messages
    params = {"channel": CHANNEL_ID, "limit": 30}
    if oldest != "0":
        params["oldest"] = oldest

    r = requests.get("https://slack.com/api/conversations.history", headers=headers, params=params, timeout=10)
    data = r.json()
    if not data.get("ok"):
        logger.error("conversations.history failed: %s", data.get("error"))
        return

    messages = data.get("messages", [])
    if not messages:
        return

    # Update last check timestamp
    latest_ts = messages[0].get("ts", "0")
    LAST_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_CHECK_FILE.write_text(latest_ts)

    # Check each message for reactions
    qualified = load_qualified()
    applied = load_applied()
    qualified_by_id_prefix = {}
    for j in qualified:
        qualified_by_id_prefix[j.get("id", "")[:8]] = j

    new_applied = 0
    for msg in messages:
        reactions = msg.get("reactions", [])
        if not reactions:
            continue

        text = msg.get("text", "")
        match = re.search(r"jobs\.py applied (\w{8})", text)
        if not match:
            continue
        job_id_prefix = match.group(1)
        job = qualified_by_id_prefix.get(job_id_prefix)
        if not job:
            continue

        reaction_names = {r["name"] for r in reactions}

        # ✅ = mark as applied
        has_check = bool(reaction_names & APPLIED_REACTIONS)
        if has_check and job["id"] not in applied:
            # Mark as applied
            applied[job["id"]] = {
                "title": job["text"],
                "company": job.get("_company", ""),
                "score": job.get("_score", 0),
                "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "url": job.get("absolute_url", ""),
                "source": "slack_reaction",
            }
            new_applied += 1
            logger.info("✅ Marked via reaction: %s @ %s", job["text"], job.get("_company"))

            # Send confirmation
            webhook_file = Path.home() / ".auto-apply" / "slack_webhook"
            if webhook_file.exists():
                webhook = webhook_file.read_text().strip()
                requests.post(webhook, json={"text": f"✅ Marked as applied (via reaction): *{job['text']}* @ _{job.get('_company', '')}_"}, timeout=5)

        # 📞 = generate interview prep
        if "telephone_receiver" in reaction_names or "phone" in reaction_names:
            prep_marker = SCRIPT_DIR / "data" / f"interview_prep_{job_id_prefix}.md"
            if not prep_marker.exists():
                logger.info("📞 Interview prep requested: %s @ %s", job["text"], job.get("_company"))
                try:
                    from interview_prep import generate_prep, send_slack as send_prep_slack
                    prep = generate_prep(job)
                    prep_marker.write_text(f"# Interview Prep: {job['text']} @ {job.get('_company', '')}\n\n{prep}")
                    header = f"*🎓 Interview Prep — {job['text']} @ {job.get('_company', '')}*\n\n"
                    webhook_file = Path.home() / ".auto-apply" / "slack_webhook"
                    webhook = webhook_file.read_text().strip()
                    if len(prep) > 3000:
                        requests.post(webhook, json={"text": header + prep[:3000] + "..."}, timeout=10)
                        requests.post(webhook, json={"text": "..." + prep[3000:]}, timeout=10)
                    else:
                        requests.post(webhook, json={"text": header + prep}, timeout=10)
                    logger.info("📞 Interview prep sent!")
                except Exception as e:
                    logger.error("Interview prep failed: %s", e)

    if new_applied:
        save_applied(applied)
        logger.info("Marked %d jobs as applied from reactions", new_applied)


def main():
    if "--daemon" in sys.argv:
        # Daemonize
        pid = os.fork()
        if pid > 0:
            print(f"Reaction poller started (PID: {pid})")
            sys.exit(0)
        os.setsid()

    logger.info("Reaction poller started. Watching channel %s every %ds.", CHANNEL_ID, POLL_INTERVAL)
    logger.info("React with ✅ on any job notification to mark it as applied.")

    while True:
        try:
            poll_reactions()
        except Exception as e:
            logger.error("Poll error: %s", e)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
