"""Browser-based Lever application submission using undetected-chromedriver."""

import logging
import os
import time

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

CHROME_PATH = "/tmp/opt/google/chrome/chrome"


class BrowserApplier:
    """Manages a browser session for submitting Lever applications."""

    def __init__(self, headless: bool = False):
        if not os.environ.get("DISPLAY"):
            os.environ["DISPLAY"] = ":0"

        opts = uc.ChromeOptions()
        if os.path.exists(CHROME_PATH):
            opts.binary_location = CHROME_PATH
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1920,1080")
        self.driver = uc.Chrome(options=opts, headless=headless)
        self.wait = WebDriverWait(self.driver, 20)

    def apply(self, company: str, posting_id: str, profile: dict, cover_letter: str = "") -> dict:
        """Fill and submit a Lever application form.

        Returns dict with 'ok' bool and 'error' string on failure.
        """
        url = f"https://jobs.lever.co/{company}/{posting_id}/apply"
        logger.info("  🌐 Opening %s", url)

        try:
            self.driver.get(url)
            self.wait.until(EC.presence_of_element_located((By.ID, "application-form")))
        except Exception as e:
            return {"ok": False, "error": f"Form did not load: {e}"}

        # Fill standard fields
        name = f"{profile['first_name']} {profile['last_name']}"
        fields = {
            "name": name,
            "email": profile["email"],
            "phone": profile.get("phone", ""),
            "org": profile.get("current_company", ""),
            "urls[LinkedIn]": profile.get("linkedin_url", ""),
            "urls[GitHub]": profile.get("github_url", ""),
            "urls[Portfolio]": profile.get("website_url", ""),
            "comments": cover_letter,
        }

        for field_name, value in fields.items():
            if not value:
                continue
            try:
                el = self.driver.find_element(By.NAME, field_name)
                el.clear()
                el.send_keys(value)
            except Exception:
                pass

        # Upload resume
        resume_path = profile.get("resume_path", "")
        if resume_path:
            try:
                self.driver.find_element(By.NAME, "resume").send_keys(resume_path)
                logger.info("  ✓ Resume uploaded")
                time.sleep(2)
            except Exception as e:
                logger.warning("  Resume upload failed: %s", e)

        # Click submit
        try:
            btn = self.driver.find_element(By.ID, "btn-submit")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn)
        except Exception as e:
            return {"ok": False, "error": f"Submit click failed: {e}"}

        # Wait for /thanks redirect (success) or timeout
        logger.info("  ⏳ Waiting for submission (CAPTCHA may appear in browser)...")
        for i in range(90):  # 3 min
            time.sleep(2)
            if "/thanks" in self.driver.current_url:
                return {"ok": True}
            if i and i % 15 == 0:
                logger.info("  ⏳ Still waiting... (%ds)", i * 2)

        return {"ok": False, "error": "Timed out waiting for submission confirmation"}

    def quit(self):
        try:
            self.driver.quit()
        except Exception:
            pass
