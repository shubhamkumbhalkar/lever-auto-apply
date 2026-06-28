#!/usr/bin/env python3
"""Auto-Apply CLI — Automatically apply to matching jobs on Lever and Greenhouse."""

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
    """Auto-Apply — Find and apply to matching jobs on Lever & Greenhouse."""
    pass


@cli.command()
@click.option("--profile", "-p", required=True, help="Path to profile YAML config")
@click.option("--dry-run", is_flag=True, help="Preview matches without submitting applications")
@click.option("--watch", is_flag=True, help="Run continuously on a schedule")
@click.option("--platform", type=click.Choice(["all", "lever", "greenhouse", "ashby"]), default="all",
              help="Which platform to scan (default: all)")
@click.option("--backend", type=click.Choice(["local", "anthropic"]), default="local",
              help="AI backend: 'local' (kiro-cli, free) or 'anthropic' (needs API key)")
def apply(profile, dry_run, watch, platform, backend):
    """Scan job boards and apply to matching positions."""
    if dry_run:
        click.echo("🔍 DRY RUN MODE — no applications will be submitted\n")

    platforms = platform if platform != "all" else "Lever + Greenhouse"
    click.echo(f"🎯 Platforms: {platforms}")
    click.echo(f"🤖 AI Backend: {backend}\n")

    if watch:
        from src.pipeline import load_config
        config = load_config(profile)
        interval = config.get("watch_interval_minutes", 30)
        click.echo(f"👀 Watch mode: running every {interval} minutes. Ctrl+C to stop.\n")
        while True:
            try:
                run_pipeline(profile, dry_run=dry_run, platform=platform, backend=backend)
                click.echo(f"\n⏳ Next run in {interval} minutes...\n")
                time.sleep(interval * 60)
            except KeyboardInterrupt:
                click.echo("\n👋 Stopped.")
                break
    else:
        run_pipeline(profile, dry_run=dry_run, platform=platform, backend=backend)


@cli.command("list-companies")
@click.option("--platform", type=click.Choice(["all", "lever", "greenhouse"]), default="all")
def list_companies(platform):
    """Show all monitored company boards."""
    companies = load_companies()

    if platform in ("all", "lever"):
        lever = companies.get("lever", [])
        click.echo(f"\n📋 Lever — {len(lever)} companies:")
        for c in sorted(lever):
            click.echo(f"  • {c}  →  https://jobs.lever.co/{c}")

    if platform in ("all", "greenhouse"):
        gh = companies.get("greenhouse", [])
        click.echo(f"\n🌱 Greenhouse — {len(gh)} boards:")
        for c in sorted(gh):
            click.echo(f"  • {c}  →  https://boards.greenhouse.io/{c}")

    total = len(companies.get("lever", [])) + len(companies.get("greenhouse", []))
    click.echo(f"\n  Total: {total} companies across all platforms")


@cli.command()
def history():
    """Show application history."""
    records = load_history()
    if not records:
        click.echo("No applications yet.")
        return

    click.echo(f"📊 {len(records)} applications on record:\n")

    for r in reversed(records[-20:]):
        status_icon = {"submitted": "✅", "failed": "❌", "skipped": "⏭️", "dry_run": "🔍"}.get(r["status"], "❓")
        plat = r.get("platform", "lever")
        plat_icon = "🌱" if plat == "greenhouse" else "🔵"
        click.echo(f"  {status_icon} {plat_icon} [{r['ats_score']:3d}] {r['job_title']} @ {r['company']} — {r['applied_at'][:10]}")
        if r.get("error"):
            click.echo(f"         Error: {r['error']}")


if __name__ == "__main__":
    cli()
