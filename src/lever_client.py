"""Lever Postings API client."""

import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.lever.co/v0/postings"
REQUEST_DELAY = 0.6  # seconds between requests


class LeverClient:
    def __init__(self):
        self.session = requests.Session()
        self._last_request_time = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def list_jobs(self, site: str) -> list[dict]:
        """Fetch all published job postings for a Lever site."""
        self._throttle()
        url = f"{BASE_URL}/{site}"
        try:
            resp = self.session.get(url, params={"mode": "json"}, timeout=30)
            if resp.status_code == 404:
                logger.warning("Site '%s' not found on Lever", site)
                return []
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Failed to fetch jobs for '%s': %s", site, e)
            return []

    def apply(
        self,
        site: str,
        posting_id: str,
        name: str,
        email: str,
        phone: str,
        org: str,
        resume_path: Path,
        urls: dict[str, str],
        comments: str,
        consent: dict[str, bool],
    ) -> dict:
        """Submit an application to a Lever job posting.

        Returns dict with 'ok', 'applicationId' on success,
        or 'ok': False, 'error' on failure.
        """
        self._throttle()
        url = f"{BASE_URL}/{site}/{posting_id}"

        data = {
            "name": name,
            "email": email,
            "phone": phone,
            "org": org,
            "comments": comments,
            "source": "Career Site",
            "silent": "true",
        }

        for key, val in urls.items():
            data[f"urls[{key}]"] = val

        for key, val in consent.items():
            data[f"consent[{key}]"] = str(val).lower()

        files = {}
        if resume_path.exists():
            files["resume"] = (resume_path.name, resume_path.open("rb"), "application/pdf")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = self.session.post(url, data=data, files=files, timeout=60)

                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Rate limited on %s/%s, retrying in %ds", site, posting_id, wait)
                    time.sleep(wait)
                    continue

                if resp.status_code >= 400:
                    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                    return {"ok": False, "error": body.get("error", f"HTTP {resp.status_code}")}

                return resp.json()

            except requests.RequestException as e:
                logger.error("Request failed for %s/%s: %s", site, posting_id, e)
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return {"ok": False, "error": str(e)}

        return {"ok": False, "error": "Max retries exceeded"}
