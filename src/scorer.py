"""ATS scoring and cover letter generation via Claude."""

import json
import logging

import anthropic

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


class ClaudeScorer:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def score_ats(self, resume_text: str, job_description: str) -> dict:
        """Score resume against job description. Returns {'score': int, 'reasoning': str}."""
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
            # Strip markdown code fences if present
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
        """Generate a tailored cover letter."""
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
