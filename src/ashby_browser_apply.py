"""Browser-based Ashby application submission using undetected-chromedriver."""

import logging
import os
import time

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = logging.getLogger(__name__)

CHROME_PATH = "/tmp/opt/google/chrome/chrome"


class AshbyBrowserApplier:
    """Manages a browser session for submitting Ashby applications."""

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

    def apply(self, job: dict, profile: dict, cover_letter: str = "") -> dict:
        """Fill and submit an Ashby application form."""
        job_url = job.get("absolute_url", "")
        if not job_url:
            board = job.get("_board", "")
            job_id = job.get("id", "")
            job_url = f"https://jobs.ashbyhq.com/{board}/{job_id}/application"

        if "/application" not in job_url:
            job_url = job_url.rstrip("/") + "/application"

        logger.info("  🌐 Opening %s", job_url)
        try:
            self.driver.get(job_url)
            self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "form, [data-testid='application-form']"))
            )
        except Exception as e:
            return {"ok": False, "error": f"Form did not load: {e}"}

        time.sleep(2)

        # Fill standard fields by label/placeholder matching
        field_map = {
            "first name": profile["first_name"],
            "last name": profile["last_name"],
            "email": profile["email"],
            "phone": profile.get("phone", ""),
            "linkedin": profile.get("linkedin_url", ""),
            "github": profile.get("github_url", ""),
            "website": profile.get("website_url", ""),
            "current company": profile.get("current_company", ""),
            "location": profile.get("location", ""),
        }

        inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[type='tel'], input[type='url']")
        for inp in inputs:
            label_text = self._get_label_for(inp).lower()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            combined = f"{label_text} {placeholder}"

            for key, val in field_map.items():
                if val and key in combined:
                    inp.clear()
                    inp.send_keys(val)
                    break

        # Upload resume
        resume_path = profile.get("resume_path", "")
        if resume_path:
            try:
                file_inputs = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_inputs:
                    file_inputs[0].send_keys(resume_path)
                    logger.info("  ✓ Resume uploaded")
                    time.sleep(2)
            except Exception as e:
                logger.warning("  Resume upload failed: %s", e)

        # Fill cover letter textarea if present
        if cover_letter:
            textareas = self.driver.find_elements(By.TAG_NAME, "textarea")
            for ta in textareas:
                label_text = self._get_label_for(ta).lower()
                if any(k in label_text for k in ["cover", "why", "interest", "about you", "additional"]):
                    ta.clear()
                    ta.send_keys(cover_letter)
                    logger.info("  ✓ Cover letter filled")
                    break
            else:
                # Use first textarea
                if textareas:
                    textareas[0].clear()
                    textareas[0].send_keys(cover_letter)

        # Submit
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit'], button[data-testid='submit-application']")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn)
            logger.info("  ✓ Clicked submit")
        except Exception as e:
            return {"ok": False, "error": f"Submit click failed: {e}"}

        # Wait for confirmation
        for i in range(60):
            time.sleep(2)
            page = self.driver.page_source.lower()
            if any(s in page for s in ["thank you", "application submitted", "received your application", "successfully submitted"]):
                return {"ok": True}
            if i and i % 15 == 0:
                logger.info("  ⏳ Still waiting... (%ds)", i * 2)

        return {"ok": False, "error": "Timed out waiting for confirmation"}

    def _get_label_for(self, element) -> str:
        """Get the label text associated with an input element."""
        el_id = element.get_attribute("id") or ""
        if el_id:
            try:
                label = self.driver.find_element(By.CSS_SELECTOR, f"label[for='{el_id}']")
                return label.text
            except Exception:
                pass
        try:
            parent = element.find_element(By.XPATH, "./ancestor::div[.//label][1]")
            label = parent.find_element(By.TAG_NAME, "label")
            return label.text
        except Exception:
            return ""

    def quit(self):
        try:
            self.driver.quit()
        except Exception:
            pass
