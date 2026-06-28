"""Workday Job Board API client."""

import logging
import re

import requests

logger = logging.getLogger(__name__)


class WorkdayClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

    def list_jobs(self, board_config: str) -> list[dict]:
        """Fetch jobs from a Workday career site.

        board_config format: "subdomain.wd5/site_name"
        e.g. "nvidia.wd5/NVIDIAExternalCareerSite"
        """
        try:
            parts = board_config.split("/", 1)
            sub_wd = parts[0]  # e.g. "nvidia.wd5"
            site = parts[1] if len(parts) > 1 else "External"
            subdomain = sub_wd.split(".")[0]

            base_url = f"https://{sub_wd}.myworkdayjobs.com/wday/cxs/{subdomain}/{site}/jobs"
        except (IndexError, ValueError):
            logger.error("Invalid Workday board config: %s", board_config)
            return []

        jobs = []
        offset = 0
        limit = 20
        while True:
            try:
                resp = self.session.post(base_url, json={"limit": limit, "offset": offset}, timeout=30)
                if resp.status_code != 200:
                    break
                data = resp.json()
                postings = data.get("jobPostings", [])
                if not postings:
                    break
                for j in postings:
                    loc = j.get("locationsText", "") or j.get("bulletFields", [""])[0] if j.get("bulletFields") else ""
                    jobs.append({
                        "id": j.get("bulletFields", [""])[0] + "_" + j.get("title", "")[:20] if not j.get("externalPath") else j["externalPath"],
                        "text": j.get("title", ""),
                        "description": "",
                        "descriptionPlain": "",
                        "categories": {"location": loc},
                        "absolute_url": f"https://{sub_wd}.myworkdayjobs.com{j.get('externalPath', '')}",
                        "_company": subdomain,
                        "_platform": "workday",
                    })
                offset += limit
                if offset >= data.get("total", 0):
                    break
            except Exception as e:
                logger.error("Workday fetch failed for '%s': %s", board_config, e)
                break
        return jobs
