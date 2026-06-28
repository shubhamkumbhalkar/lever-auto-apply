"""Browser-based Greenhouse application submission using undetected-chromedriver."""

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

# Default answers for common Greenhouse custom questions
DEFAULT_ANSWERS = {
    "legally authorized to work in the united states": "Yes",
    "currently located in the us": "Yes",
    "require sponsorship": "No",
    "willing to relocate": "Yes",
    "based in or willing to relocate": "Yes",
    "18 years of age": "Yes",
    "how did you hear": "Career Site",
}


class GreenhouseBrowserApplier:
    """Manages a browser session for submitting Greenhouse applications."""

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

    def apply(self, job: dict, profile: dict, cover_letter: str = "",
              custom_answers: dict | None = None) -> dict:
        """Fill and submit a Greenhouse application form."""
        absolute_url = job.get("absolute_url", "")
        job_id = job.get("id", "")
        board = job.get("_board", "")

        if not absolute_url:
            return {"ok": False, "error": "No absolute_url for job"}

        hosted_url = f"https://boards.greenhouse.io/{board}/jobs/{job_id}" if board else ""

        for url in [hosted_url, absolute_url]:
            if not url:
                continue
            logger.info("  🌐 Trying %s", url)
            try:
                self.driver.get(url)
                self.wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "#application-form, #application, form.application-form")
                    )
                )
                logger.info("  ✓ Application form loaded")
                break
            except Exception:
                continue
        else:
            return {"ok": False, "error": "Form did not load at any URL"}

        # 1. Fill standard text fields
        for fid, val in [
            ("first_name", profile["first_name"]),
            ("last_name", profile["last_name"]),
            ("email", profile["email"]),
            ("phone", profile.get("phone", "")),
        ]:
            if val:
                self._fill_field(fid, val)

        # 2. Location field (autocomplete select)
        self._fill_location(profile.get("location", "Chicago, Illinois, United States"))

        # 3. LinkedIn / GitHub / Website
        for label_text, val in [
            ("linkedin", profile.get("linkedin_url", "")),
            ("github", profile.get("github_url", "")),
            ("website", profile.get("website_url", "")),
        ]:
            if val:
                self._fill_by_label(label_text, val)

        # 4. Upload resume
        resume_path = profile.get("resume_path", "")
        if resume_path:
            try:
                el = self.driver.find_element(By.ID, "resume")
                el.send_keys(resume_path)
                logger.info("  ✓ Resume uploaded")
                time.sleep(2)
            except Exception:
                # Fallback: first file input
                try:
                    fi = self.driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if fi:
                        fi[0].send_keys(resume_path)
                        logger.info("  ✓ Resume uploaded (fallback)")
                        time.sleep(2)
                except Exception as e:
                    logger.warning("  Resume upload failed: %s", e)

        # 5. Fill custom questions (textareas and selects)
        answers = {**(custom_answers or {})}
        if cover_letter:
            # Use cover letter as default for open-ended "why" questions
            answers.setdefault("why do you want to work", cover_letter)
            answers.setdefault("why are you interested", cover_letter)
        self._fill_custom_questions(answers)

        # 6. Click submit
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", btn)
            time.sleep(1)
            self.driver.execute_script("arguments[0].click();", btn)
            logger.info("  ✓ Clicked submit")
        except Exception as e:
            return {"ok": False, "error": f"Submit click failed: {e}"}

        # 7. Wait for confirmation
        logger.info("  ⏳ Waiting for submission (CAPTCHA may appear)...")
        for i in range(90):
            time.sleep(2)
            page = self.driver.page_source.lower()
            url_now = self.driver.current_url.lower()
            if any(s in page for s in [
                "application has been submitted",
                "thank you for applying",
                "thanks for applying",
                "your application has been received",
            ]):
                return {"ok": True}
            if "confirmation" in url_now or "thanks" in url_now:
                return {"ok": True}
            if i and i % 15 == 0:
                # Check for validation errors still showing
                errs = self.driver.find_elements(By.CSS_SELECTOR, ".helper-text--error")
                err_texts = [e.text for e in errs if e.text.strip()]
                if err_texts:
                    return {"ok": False, "error": f"Validation errors: {err_texts[:3]}"}
                logger.info("  ⏳ Still waiting... (%ds)", i * 2)

        return {"ok": False, "error": "Timed out waiting for submission confirmation"}

    def _fill_field(self, field_id: str, value: str):
        """Fill a field by id."""
        for sel in [f"#{field_id}", f"[id*='{field_id}']"]:
            try:
                el = self.driver.find_element(By.CSS_SELECTOR, sel)
                el.clear()
                el.send_keys(value)
                return
            except Exception:
                continue

    def _fill_location(self, location: str):
        """Fill the location autocomplete field."""
        try:
            el = self.driver.find_element(By.ID, "candidate-location")
            el.clear()
            el.send_keys(location)
            time.sleep(1.5)
            # Select first autocomplete option
            try:
                option = self.wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "[class*='select__option'], [class*='autocomplete'] li, [role='option']")
                    )
                )
                option.click()
                logger.info("  ✓ Location set: %s", location)
            except Exception:
                # Press Enter to accept typed value
                el.send_keys(Keys.RETURN)
                logger.info("  ✓ Location typed: %s", location)
        except Exception:
            pass

    def _fill_by_label(self, label_text: str, value: str):
        """Find an input by its label text and fill it."""
        try:
            labels = self.driver.find_elements(By.TAG_NAME, "label")
            for label in labels:
                if label_text.lower() in label.text.lower():
                    for_id = label.get_attribute("for")
                    if for_id:
                        try:
                            el = self.driver.find_element(By.ID, for_id)
                            el.clear()
                            el.send_keys(value)
                            return
                        except Exception:
                            pass
                    parent = label.find_element(By.XPATH, "..")
                    inputs = parent.find_elements(By.CSS_SELECTOR, "input, textarea")
                    if inputs:
                        inputs[0].clear()
                        inputs[0].send_keys(value)
                        return
        except Exception:
            pass

    def _fill_custom_questions(self, extra_answers: dict):
        """Fill custom questions — textareas and select dropdowns."""
        all_answers = {**DEFAULT_ANSWERS, **extra_answers}

        # Handle textareas (open-ended questions)
        textareas = self.driver.find_elements(By.CSS_SELECTOR, "textarea[id^='question_']")
        for ta in textareas:
            ta_id = ta.get_attribute("id")
            label_el = self.driver.find_elements(By.CSS_SELECTOR, f"label[for='{ta_id}']")
            label_text = label_el[0].text.lower() if label_el else ""

            for key, answer in all_answers.items():
                if key.lower() in label_text:
                    ta.clear()
                    ta.send_keys(answer)
                    logger.info("  ✓ Answered: %s", label_text[:60])
                    break
            else:
                # If no specific answer, use a generic response for required fields
                if ta.get_attribute("required") or ta.get_attribute("aria-required") == "true":
                    ta.send_keys("I'm excited about this opportunity and would love to discuss further.")
                    logger.info("  ✓ Generic answer for: %s", label_text[:60])

        # Handle select dropdowns (Yes/No questions)
        # Greenhouse uses react-select, so we click the control then pick an option
        labels = self.driver.find_elements(By.CSS_SELECTOR, "label[class*='select__label']")
        for label in labels:
            label_text = label.text.lower().rstrip("*").strip()
            if not label_text:
                continue

            answer = None
            for key, val in all_answers.items():
                if key.lower() in label_text:
                    answer = val
                    break

            if not answer:
                continue

            # Find the select control near this label
            label_id = label.get_attribute("for") or label.get_attribute("id") or ""
            try:
                # Click the select control to open dropdown
                parent = label.find_element(By.XPATH, "./..")
                control = parent.find_element(By.CSS_SELECTOR, "[class*='select__control']")
                self.driver.execute_script("arguments[0].scrollIntoView(true);", control)
                time.sleep(0.3)
                control.click()
                time.sleep(0.5)

                # Find and click the matching option
                options = self.driver.find_elements(By.CSS_SELECTOR, "[class*='select__option']")
                for opt in options:
                    if opt.text.strip().lower() == answer.lower():
                        opt.click()
                        logger.info("  ✓ Selected '%s' for: %s", answer, label_text[:60])
                        break
                else:
                    # Click first option as fallback
                    if options:
                        options[0].click()
                        logger.info("  ✓ Selected first option for: %s", label_text[:60])
                time.sleep(0.3)
            except Exception as e:
                logger.debug("  Could not fill select for '%s': %s", label_text[:40], e)

    def quit(self):
        try:
            self.driver.quit()
        except Exception:
            pass
