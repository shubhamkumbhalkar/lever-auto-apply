#!/usr/bin/env python3
"""Weekly stats report — sends application summary to Slack every Sunday."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
QUALIFIED_FILE = SCRIPT_DIR / "data" / "qualified_jobs.json"
APPLIED_FILE = SCRIPT_DIR / "data" / "applied_jobs.json"
SLACK_WEBHOOK_FILE = Path.home() / ".auto-apply" / "slack_webhook"


def main():
    qualified = json.loads(QUALIFIED_FILE.read_text()) if QUALIFIED_FILE.exists() else []
    applied = json.loads(APPLIED_FILE.read_text()) if APPLIED_FILE.exists() else {}

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # This week's applications
    this_week = {jid: info for jid, info in applied.items()
                 if info.get("applied_at", "") >= week_ago.isoformat()[:10]}

    # Stats
    total_qualified = len(qualified)
    total_applied = len(applied)
    pending = total_qualified - sum(1 for j in qualified if j.get("id") in applied)
    week_applied = len(this_week)

    # Top companies applied to this week
    companies_this_week = Counter(info["company"] for info in this_week.values())
    # Score distribution
    scores = [info.get("score", 0) for info in this_week.values() if info.get("score")]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Platform breakdown
    platforms = Counter(j.get("_platform", "?") for j in qualified)

    # Build message
    lines = [
        f"*📊 Weekly Job Report — {now.strftime('%B %d, %Y')}*\n",
        f"*This week:*",
        f"  • Applications submitted: *{week_applied}*",
        f"  • Avg ATS score: *{avg_score:.0f}*" if scores else "",
        f"",
        f"*All time:*",
        f"  • Total qualified jobs found: *{total_qualified}*",
        f"  • Total applied: *{total_applied}*",
        f"  • Pending (not yet applied): *{pending}*",
        f"",
    ]

    if companies_this_week:
        lines.append("*Companies applied to this week:*")
        for company, count in companies_this_week.most_common(10):
            lines.append(f"  • _{company}_ × {count}")
        lines.append("")

    if platforms:
        lines.append("*Jobs by platform:*")
        for plat, count in platforms.most_common():
            lines.append(f"  • {plat}: {count}")
        lines.append("")

    # Pending high-score jobs (gentle nudge)
    high_pending = [j for j in qualified if j.get("id") not in applied and j.get("_score", 0) >= 80]
    if high_pending:
        lines.append(f"*🔥 {len(high_pending)} high-score jobs still pending (≥80):*")
        for j in sorted(high_pending, key=lambda x: -x.get("_score", 0))[:5]:
            url = j.get("absolute_url") or j.get("hostedUrl") or ""
            lines.append(f"  • *{j.get('_score')}* — {j['text']} @ _{j.get('_company')}_  <{url}|Apply>")

    msg = "\n".join(l for l in lines if l is not None)

    # Send
    webhook = SLACK_WEBHOOK_FILE.read_text().strip()
    resp = requests.post(webhook, json={"text": msg, "mrkdwn": True}, timeout=10)
    print(f"Weekly report sent: {resp.status_code}")


if __name__ == "__main__":
    main()
