"""Ashby Job Board API client."""

import logging
import time

import requests

logger = logging.getLogger(__name__)

BOARD_API_URL = "https://api.ashbyhq.com/posting-api/job-board"
REQUEST_DELAY = 0.6


class AshbyClient:
    def __init__(self):
        self.session = requests.Session()
        self._last_request_time = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def list_jobs(self, board_slug: str) -> list[dict]:
        """Fetch all published jobs for an Ashby board.

        Returns normalized dicts compatible with the pipeline.
        """
        self._throttle()
        url = f"{BOARD_API_URL}/{board_slug}"
        try:
            resp = self.session.get(url, timeout=30)
            if resp.status_code == 404:
                logger.warning("Board '%s' not found on Ashby", board_slug)
                return []
            resp.raise_for_status()
            data = resp.json()
            return [self._normalize(j, board_slug) for j in data.get("jobs", [])]
        except requests.RequestException as e:
            logger.error("Failed to fetch Ashby jobs for '%s': %s", board_slug, e)
            return []

    @staticmethod
    def _normalize(job: dict, board_slug: str) -> dict:
        """Normalize Ashby job to match Lever/Greenhouse shape."""
        location = job.get("location", "") or ""
        if isinstance(location, dict):
            location = location.get("name", "")

        return {
            "id": job.get("id", ""),
            "text": job.get("title", ""),
            "description": job.get("descriptionHtml", ""),
            "descriptionPlain": job.get("descriptionPlain", "") or job.get("descriptionHtml", ""),
            "categories": {"location": location},
            "absolute_url": job.get("jobUrl", ""),
            "_board": board_slug,
        }
