"""Greenhouse Job Board API client."""

import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BOARD_API_URL = "https://boards-api.greenhouse.io/v1/boards"
REQUEST_DELAY = 0.6


class GreenhouseClient:
    def __init__(self):
        self.session = requests.Session()
        self._last_request_time = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def list_jobs(self, board_token: str) -> list[dict]:
        """Fetch all published jobs for a Greenhouse board.

        Returns normalized dicts with keys: id, text, description,
        descriptionPlain, categories (with location), country, _board.
        """
        self._throttle()
        url = f"{BOARD_API_URL}/{board_token}/jobs"
        try:
            resp = self.session.get(url, params={"content": "true"}, timeout=30)
            if resp.status_code == 404:
                logger.warning("Board '%s' not found on Greenhouse", board_token)
                return []
            resp.raise_for_status()
            data = resp.json()
            return [self._normalize(j, board_token) for j in data.get("jobs", [])]
        except requests.RequestException as e:
            logger.error("Failed to fetch Greenhouse jobs for '%s': %s", board_token, e)
            return []

    @staticmethod
    def _normalize(job: dict, board_token: str) -> dict:
        """Normalize Greenhouse job to match Lever's shape for pipeline compatibility."""
        location = ""
        if job.get("location"):
            location = job["location"].get("name", "")

        return {
            "id": str(job["id"]),
            "text": job.get("title", ""),
            "description": job.get("content", ""),
            "descriptionPlain": job.get("content", ""),
            "categories": {"location": location},
            "absolute_url": job.get("absolute_url", ""),
            "_board": board_token,
        }
