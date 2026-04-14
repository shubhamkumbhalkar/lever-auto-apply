"""Email notification for application summaries."""

import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_summary_email(config: dict, results: list[dict]):
    """Send a summary email of the application run."""
    if not results:
        return

    smtp_cfg = config.get("smtp", {})
    to_email = config.get("notification_email", "")
    if not to_email or not smtp_cfg.get("host"):
        logger.info("Email notifications not configured, skipping")
        return

    submitted = [r for r in results if r["status"] == "submitted"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]

    lines = [
        f"Lever Auto-Apply Run Summary",
        f"{'=' * 40}",
        f"Total jobs evaluated: {len(results)}",
        f"Applications submitted: {len(submitted)}",
        f"Skipped (below threshold): {len(skipped)}",
        f"Failed: {len(failed)}",
        "",
    ]

    if submitted:
        lines.append("✅ SUBMITTED:")
        for r in submitted:
            lines.append(f"  - {r['job_title']} @ {r['company']} (ATS: {r['ats_score']})")
        lines.append("")

    if skipped:
        lines.append("⏭️ SKIPPED (below threshold):")
        for r in skipped:
            lines.append(f"  - {r['job_title']} @ {r['company']} (ATS: {r['ats_score']})")
        lines.append("")

    if failed:
        lines.append("❌ FAILED:")
        for r in failed:
            lines.append(f"  - {r['job_title']} @ {r['company']}: {r.get('error', 'unknown')}")

    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"Auto-Apply: {len(submitted)} submitted, {len(failed)} failed"
    msg["From"] = smtp_cfg.get("username", "")
    msg["To"] = to_email

    password = smtp_cfg.get("password") or os.environ.get("SMTP_PASSWORD", "")
    if not password:
        logger.warning("No SMTP password configured, skipping email")
        return

    try:
        with smtplib.SMTP(smtp_cfg["host"], smtp_cfg.get("port", 587)) as server:
            server.starttls()
            server.login(smtp_cfg["username"], password)
            server.send_message(msg)
        logger.info("Summary email sent to %s", to_email)
    except Exception as e:
        logger.error("Failed to send email: %s", e)
