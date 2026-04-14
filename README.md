# Lever Auto-Apply

A Python CLI agent that automatically finds and applies to matching jobs on Lever-based job portals. Uses Claude for semantic ATS scoring and personalized cover letter generation.

## How It Works

1. Scans 70+ company Lever boards for new job postings
2. Filters by your target role keywords
3. Scores each match against your resume using Claude (semantic ATS scoring)
4. If score > 75%, generates a tailored cover letter and submits the application
5. Tracks all applications and sends email summaries

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and edit your profile
cp profile.example.yaml profile.yaml
# Edit profile.yaml with your details

# Set your Anthropic API key (or put it in profile.yaml)
export ANTHROPIC_API_KEY="sk-ant-..."

# Place your resume PDF in the project directory
cp /path/to/your/resume.pdf ./resume.pdf
```

## Usage

```bash
# Preview matches without applying (recommended first run)
python cli.py apply --profile profile.yaml --dry-run

# Run once and apply
python cli.py apply --profile profile.yaml

# Run every 30 minutes
python cli.py apply --profile profile.yaml --watch

# Dry run + watch (monitor without applying)
python cli.py apply --profile profile.yaml --watch --dry-run

# List monitored companies
python cli.py list-companies

# View application history
python cli.py history
```

## Configuration

### Profile (`profile.yaml`)

Your personal info, resume path, target roles, and notification settings. See `profile.example.yaml` for all options.

### Companies (`companies.yaml`)

List of Lever site slugs to monitor. Add any company that uses Lever — find their slug from `jobs.lever.co/{slug}`.

### Key Settings

| Setting | Description |
|---|---|
| `target_roles` | Keywords to match against job titles |
| `ats_threshold` | Minimum ATS score to auto-apply (default: 75) |
| `watch_interval_minutes` | How often to scan in watch mode (default: 30) |
| `consent.marketing` | Consent for future contact (default: true) |
| `consent.store` | Consent for data storage (default: true) |

## Multi-User Support

Create separate profile YAML files for different people:

```bash
python cli.py apply --profile alice-profile.yaml
python cli.py apply --profile bob-profile.yaml
```

## Data Files

| File | Purpose |
|---|---|
| `data/history.json` | Full application history with cover letters |
| `data/seen_ids.json` | Tracks seen posting IDs to avoid duplicates |

## Notes

- The `source` field is set to "Career Site" to avoid being filtered out
- Applications are submitted with `silent: true` (no confirmation email to candidate from Lever)
- Some companies may require an API key for POST submissions — the tool logs these failures and moves on
- Rate limited to ~1-2 requests/second to avoid being flagged
- 429 responses are retried with exponential backoff
