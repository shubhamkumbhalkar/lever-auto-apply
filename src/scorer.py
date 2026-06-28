"""ATS scoring and cover letter generation.

Supports two backends:
  - 'local': uses kiro-cli (free, no API key needed)
  - 'anthropic': uses Anthropic API (requires ANTHROPIC_API_KEY)
"""

import json
import logging
import re
import subprocess
import tempfile

logger = logging.getLogger(__name__)

ATS_PROMPT = """You are an ATS (Applicant Tracking System) scoring expert.

Compare the candidate's resume against the job description and return a JSON object with:
- "score": integer 0-100 representing how well the resume matches the job
- "reasoning": brief explanation of the score

Scoring criteria:
- Skills match (technical skills, tools, languages)
- Experience level alignment
- Industry/domain relevance
- Education fit
- Keywords overlap

Resume:
{resume_text}

Job Description:
{job_description}

Respond ONLY with valid JSON, no markdown."""

COVER_LETTER_PROMPT = """Write a conversational cover letter for this job application.

Candidate resume:
{resume_text}

Job title: {job_title}
Company: {company}
Job description:
{job_description}

Guidelines:
- Conversational and genuine tone, not corporate-speak
- 3-4 short paragraphs max
- Reference 2-3 specific requirements from the job and map them to the candidate's experience
- Show enthusiasm for the company and role
- No generic filler phrases like "I am writing to express my interest"
- End with a forward-looking statement, not "I look forward to hearing from you"

Return ONLY the cover letter text, no subject line or headers."""


def _call_kiro(prompt: str, timeout: int = 120) -> str:
    """Call kiro-cli chat with a prompt and return the raw response text."""
    try:
        result = subprocess.run(
            ["kiro-cli", "chat", prompt, "--legacy-ui", "--trust-tools=", "--agent", "gpu-minimal"],
            capture_output=True, text=True, timeout=timeout,
        )
        # Strip ANSI escape codes and carriage returns
        raw = result.stdout
        raw = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', raw)
        raw = raw.replace('\r', '\n')
        return raw
    except subprocess.TimeoutExpired:
        logger.error("kiro-cli timed out after %ds", timeout)
        return ""
    except FileNotFoundError:
        logger.error("kiro-cli not found. Install it or use backend='anthropic'.")
        return ""


class LocalScorer:
    """ATS scorer using kiro-cli (no API key needed)."""

    def score_ats(self, resume_text: str, job_description: str) -> dict:
        prompt = ATS_PROMPT.format(
            resume_text=resume_text[:8000],
            job_description=job_description[:4000],
        )
        raw = _call_kiro(prompt)
        # Extract JSON object containing "score"
        match = re.search(r'\{[^{}]*"score"[^{}]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError as e:
                logger.error("Failed to parse ATS JSON: %s", e)
        return {"score": 0, "reasoning": "Failed to parse kiro-cli response"}

    def generate_cover_letter(
        self, resume_text: str, job_title: str, company: str, job_description: str
    ) -> str:
        prompt = COVER_LETTER_PROMPT.format(
            resume_text=resume_text[:8000],
            job_title=job_title,
            company=company,
            job_description=job_description[:4000],
        )
        raw = _call_kiro(prompt, timeout=180)
        # Extract the cover letter — everything after the last "Thinking..." line
        # and before the credits/exit lines
        lines = raw.split('\n')
        content_lines = []
        capture = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('>') or stripped.startswith('▸'):
                # This is the response marker or credits line
                if stripped.startswith('>'):
                    # Response content after ">"
                    content_lines.append(stripped.lstrip('> '))
                    capture = True
                elif capture:
                    break
            elif capture:
                content_lines.append(stripped)

        text = '\n'.join(content_lines).strip()
        if text:
            return text

        # Fallback: grab everything that looks like prose
        prose = [l.strip() for l in lines if l.strip() and not any(
            k in l for k in ['Thinking', 'WARNING', 'hooks finished', 'Credits:', 'exit the CLI', 'changelog', 'Model:']
        )]
        return '\n'.join(prose[-20:]).strip()


class ClaudeScorer:
    """ATS scorer using Anthropic API (requires API key)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def score_ats(self, resume_text: str, job_description: str) -> dict:
        import anthropic
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": ATS_PROMPT.format(
                        resume_text=resume_text[:8000],
                        job_description=job_description[:4000],
                    ),
                }],
            )
            text = resp.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return json.loads(text)
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            logger.error("Failed to parse ATS score: %s", e)
            return {"score": 0, "reasoning": f"Parse error: {e}"}
        except anthropic.APIError as e:
            logger.error("Claude API error during scoring: %s", e)
            return {"score": 0, "reasoning": f"API error: {e}"}

    def generate_cover_letter(
        self, resume_text: str, job_title: str, company: str, job_description: str
    ) -> str:
        import anthropic
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": COVER_LETTER_PROMPT.format(
                        resume_text=resume_text[:8000],
                        job_title=job_title,
                        company=company,
                        job_description=job_description[:4000],
                    ),
                }],
            )
            return resp.content[0].text.strip()
        except anthropic.APIError as e:
            logger.error("Claude API error during cover letter generation: %s", e)
            return ""


def create_scorer(backend: str = "local", api_key: str = ""):
    """Factory to create the right scorer.

    backend: 'local' (kiro-cli) or 'anthropic' (API key required)
    """
    if backend == "anthropic":
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY required for 'anthropic' backend")
        return ClaudeScorer(api_key)
    return LocalScorer()
