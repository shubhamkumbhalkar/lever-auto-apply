"""SmartRecruiters Job Board API client."""

import logging
import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.smartrecruiters.com/v1/companies"


class SmartRecruitersClient:
    def __init__(self):
        self.session = requests.Session()

    def list_jobs(self, company: str) -> list[dict]:
        """Fetch all postings for a SmartRecruiters company."""
        jobs = []
        offset = 0
        limit = 100
        while True:
            try:
                resp = self.session.get(
                    f"{BASE_URL}/{company}/postings",
                    params={"limit": limit, "offset": offset},
                    timeout=30,
                )
                if resp.status_code != 200:
                    return []
                data = resp.json()
                content = data.get("content", [])
                if not content:
                    break
                for j in content:
                    loc = j.get("location", {})
                    city = loc.get("city", "")
                    region = loc.get("region", "")
                    country = loc.get("country", "")
                    location_str = ", ".join(filter(None, [city, region, country]))
                    jobs.append({
                        "id": j.get("id", ""),
                        "text": j.get("name", ""),
                        "description": j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
                        "descriptionPlain": j.get("jobAd", {}).get("sections", {}).get("jobDescription", {}).get("text", ""),
                        "categories": {"location": location_str},
                        "absolute_url": j.get("ref", ""),
                        "_company": company,
                        "_platform": "smartrecruiters",
                    })
                offset += limit
                if offset >= data.get("totalFound", 0):
                    break
            except Exception as e:
                logger.error("SmartRecruiters fetch failed for '%s': %s", company, e)
                break
        return jobs
