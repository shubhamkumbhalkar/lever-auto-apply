# Auto-Apply — AI-Powered Job Search Automation

A Python CLI that automatically finds, scores, and helps you apply to matching software engineering jobs across **7 job board platforms**. Uses AI for ATS scoring, cover letter generation, and interview prep.

## Features

- **Multi-platform scanning** — Lever, Greenhouse, Ashby, SmartRecruiters, Workday, Indeed/Google (via JobSpy), Hiring.cafe
- **AI ATS scoring** — Scores each job against your resume (0-100) using Claude
- **Cover letter generation** — Tailored cover letter for each qualified job
- **"Why this company?" answers** — Custom answer generated per company
- **Interview prep** — STAR stories mapped to likely questions (uses your own prep doc)
- **Slack notifications** — Individual message per qualified job with apply link
- **Reaction-based tracking** — React ✅ to mark applied, 📞 for interview prep
- **Daily automation** — Cron job scans daily, only shows new jobs
- **Deduplication** — By job ID + title+company, max 2 per company per run
- **Platform diversity** — Ensures all 7 platforms get representation in scoring
- **Weekly stats report** — Application stats every Sunday

## Architecture

```
daily_scan.py          # Main orchestrator — scan, score, notify
├── src/
│   ├── lever_client.py        # Lever Postings API
│   ├── greenhouse_client.py   # Greenhouse Board API
│   ├── ashby_client.py        # Ashby Posting API
│   ├── smartrecruiters_client.py  # SmartRecruiters API
│   ├── workday_client.py      # Workday career sites
│   ├── matcher.py             # Job filtering, US detection, resume parsing
│   └── scorer.py              # AI ATS scoring + cover letter generation
├── jobs.py            # CLI for listing, marking applied, cover letters
├── reaction_poller.py # Slack reaction watcher (✅ = applied, 📞 = prep)
├── interview_prep.py  # Interview prep generator with STAR stories
├── weekly_report.py   # Weekly stats digest
├── discover_companies.py  # Find new companies on all platforms
├── fast_scan.py       # Quick parallel scan (no scoring)
└── companies.yaml     # Company list by platform
```

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
# For Indeed/Google scraping:
pip install python-jobspy
```

### 2. Configure your profile

```bash
cp profile.example.yaml profile.yaml
# Edit with your details: name, email, resume path, target roles
```

### 3. Set up Slack notifications

Create a Slack app with an incoming webhook, then:
```bash
mkdir -p ~/.auto-apply
echo "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" > ~/.auto-apply/slack_webhook
```

For reaction tracking (optional), add a bot token:
```bash
echo "xoxb-your-bot-token" > ~/.auto-apply/slack_bot_token
export SLACK_CHANNEL_ID="your-channel-id"  # Channel where notifications go
```

Required bot scopes: `chat:write`, `reactions:read`, `channels:history`, `channels:read`, `im:history`, `im:read`

### 4. Set up daily cron

```bash
cp run_daily_scan.sh.example run_daily_scan.sh
chmod +x run_daily_scan.sh
# Edit paths in run_daily_scan.sh

# Install cron (noon PST)
(crontab -l 2>/dev/null; echo "CRON_TZ=America/Los_Angeles"; echo "0 12 * * * /path/to/run_daily_scan.sh") | crontab -

# Weekly report (Sunday 10 AM)
(crontab -l; echo "0 10 * * 0 python3 /path/to/weekly_report.py") | crontab -
```

## Usage

```bash
# Daily scan (runs automatically via cron)
python3 daily_scan.py

# Dry run (preview without sending)
python3 daily_scan.py --dry-run

# Quick scan without scoring
python3 daily_scan.py --no-score

# Fast parallel scan (just shows matches)
python3 fast_scan.py --profile profile.yaml

# List qualified jobs
python3 jobs.py list

# Generate cover letter for a job
python3 jobs.py cover <job_id>

# Mark as applied
python3 jobs.py applied <job_id>

# Application stats
python3 jobs.py status

# Interview prep
python3 interview_prep.py <job_id>

# Discover new companies
python3 discover_companies.py

# Weekly report
python3 weekly_report.py
```

## Slack Workflow

1. Get a notification per qualified job (with cover letter + apply link)
2. Click "Apply Here" → apply on your phone/laptop
3. React with ✅ → automatically marked as applied
4. React with 📞 → get interview prep sent to Slack

## AI Backend

| Backend | Flag | Requires | Notes |
|---|---|---|---|
| Local (kiro-cli) | `--backend local` (default) | `kiro-cli` installed | Free |
| Anthropic API | `--backend anthropic` | `ANTHROPIC_API_KEY` env var | Faster |

## Adding Companies

Edit `companies.yaml`:

```yaml
lever:
  - company-slug    # from jobs.lever.co/{slug}

greenhouse:
  - board-token     # from boards.greenhouse.io/{token}

ashby:
  - company-slug    # from jobs.ashbyhq.com/{slug}

smartrecruiters:
  - CompanyName     # from careers.smartrecruiters.com/{name}

workday:
  - subdomain.wd5/SiteName  # from {subdomain}.wd5.myworkdayjobs.com
```

Or auto-discover new companies:
```bash
python3 discover_companies.py
```

## Configuration

Key settings in `profile.yaml`:

| Setting | Description |
|---|---|
| `target_roles` | Keywords to match job titles |
| `ats_threshold` | Minimum score to notify (default: 75) |
| `resume_path` | Path to your PDF resume |
| `location` | Your location (for "where are you based?" questions) |

## License

MIT
