#!/usr/bin/env python3
"""Lever Auto-Apply CLI — Automatically apply to matching jobs on Lever."""

import json
import logging
import time

import click

from src.matcher import load_history
from src.pipeline import load_companies, run_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


@click.group()
def cli():
    """Lever Auto-Apply — Find and apply to matching jobs automatically."""
    pass


@cli.command()
@click.option("--profile", "-p", required=True, help="Path to profile YAML config")
@click.option("--dry-run", is_flag=True, help="Preview matches without submitting applications")
@click.option("--watch", is_flag=True, help="Run continuously on a schedule")
def apply(profile, dry_run, watch):
    """Scan Lever job boards and apply to matching positions."""
    if dry_run:
        click.echo("🔍 DRY RUN MODE — no applications will be submitted\n")

    if watch:
        from src.pipeline import load_config
        config = load_config(profile)
        interval = config.get("watch_interval_minutes", 30)
        click.echo(f"👀 Watch mode: running every {interval} minutes. Ctrl+C to stop.\n")
        while True:
            try:
                run_pipeline(profile, dry_run=dry_run)
                click.echo(f"\n⏳ Next run in {interval} minutes...\n")
                time.sleep(interval * 60)
            except KeyboardInterrupt:
                click.echo("\n👋 Stopped.")
                break
    else:
        run_pipeline(profile, dry_run=dry_run)


@cli.command("list-companies")
def list_companies():
    """Show all monitored Lever company boards."""
    companies = load_companies()
    click.echo(f"📋 Monitoring {len(companies)} companies:\n")
    for c in sorted(companies):
        click.echo(f"  • {c}  →  https://jobs.lever.co/{c}")


@cli.command()
def history():
    """Show application history."""
    records = load_history()
    if not records:
        click.echo("No applications yet.")
        return

    click.echo(f"📊 {len(records)} applications on record:\n")

    for r in reversed(records[-20:]):  # show last 20
        status_icon = {"submitted": "✅", "failed": "❌", "skipped": "⏭️", "dry_run": "🔍"}.get(r["status"], "❓")
        click.echo(f"  {status_icon} [{r['ats_score']:3d}] {r['job_title']} @ {r['company']} — {r['applied_at'][:10]}")
        if r.get("error"):
            click.echo(f"         Error: {r['error']}")


if __name__ == "__main__":
    cli()
