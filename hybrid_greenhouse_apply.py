#!/usr/bin/env python3
"""
Greenhouse Auto-Apply — Hybrid mode (DCV).
Auto-fills the form, you solve the CAPTCHA in the DCV session.

Usage: python3 hybrid_greenhouse_apply.py profile.yaml <board> <job_id> [--custom-answers answers.yaml]
"""

import os
import sys
import time

import yaml
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CHROME_PATH = "/tmp/opt/google/chrome/chrome"

DEFAULT_SELECT_ANSWERS = {
    "legally authorized to work in the united states": "Yes",
    "currently located in the us": "Yes",
    "require sponsorship": "No",
    "willing to relocate": "Yes",
    "based in or willing to relocate": "Yes",
    "18 years of age": "Yes",
}


def apply_to_job(board, job_id, profile, driver, custom_answers=None):
    url = f"https://boards.greenhouse.io/{board}/jobs/{job_id}"
    print(f"\nOpening {url}")

    driver.get(url)
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.ID, "application-form")))

    try:
        title = driver.find_element(By.CSS_SELECTOR, "h1, h2").text
    except Exception:
        title = job_id
    print(f"  Job: {title}")

    # Fill standard fields
    for fid, val in [
        ("first_name", profile["first_name"]),
        ("last_name", profile["last_name"]),
        ("email", profile["email"]),
        ("phone", profile.get("phone", "")),
    ]:
        if not val:
            continue
        try:
            el = driver.find_element(By.ID, fid)
            el.clear()
            el.send_keys(val)
        except Exception:
            pass
    print("  ✓ Basic fields filled")

    # Location autocomplete
    location = profile.get("location", "Chicago, Illinois, United States")
    try:
        loc = driver.find_element(By.ID, "candidate-location")
        loc.clear()
        loc.send_keys(location)
        time.sleep(1.5)
        try:
            opt = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[class*='select__option'], [role='option']")
            ))
            opt.click()
            print(f"  ✓ Location: {location}")
        except Exception:
            loc.send_keys(Keys.RETURN)
            print(f"  ✓ Location typed: {location}")
    except Exception:
        pass

    # LinkedIn / GitHub
    for label_text, val in [
        ("linkedin", profile.get("linkedin_url", "")),
        ("github", profile.get("github_url", "")),
    ]:
        if not val:
            continue
        try:
            for label in driver.find_elements(By.TAG_NAME, "label"):
                if label_text.lower() in label.text.lower():
                    for_id = label.get_attribute("for")
                    if for_id:
                        el = driver.find_element(By.ID, for_id)
                        el.clear()
                        el.send_keys(val)
                        break
        except Exception:
            pass
    print("  ✓ URLs filled")

    # Resume
    try:
        driver.find_element(By.ID, "resume").send_keys(profile["resume_path"])
        print("  ✓ Resume uploaded")
        time.sleep(2)
    except Exception as e:
        print(f"  ⚠ Resume upload: {e}")

    # Custom textarea questions
    answers = custom_answers or {}
    for ta in driver.find_elements(By.CSS_SELECTOR, "textarea[id^='question_']"):
        ta_id = ta.get_attribute("id")
        labels = driver.find_elements(By.CSS_SELECTOR, f"label[for='{ta_id}']")
        label_text = labels[0].text.lower() if labels else ""

        filled = False
        for key, answer in answers.items():
            if key.lower() in label_text:
                ta.clear()
                ta.send_keys(answer)
                print(f"  ✓ Answered: {label_text[:60]}")
                filled = True
                break
        if not filled and (ta.get_attribute("required") or ta.get_attribute("aria-required") == "true"):
            ta.send_keys("I'm excited about this opportunity and would love to discuss further.")
            print(f"  ✓ Generic answer: {label_text[:60]}")

    # Select dropdowns (Yes/No)
    all_selects = {**DEFAULT_SELECT_ANSWERS, **answers}
    for label in driver.find_elements(By.CSS_SELECTOR, "label[class*='select__label']"):
        label_text = label.text.lower().rstrip("*").strip()
        answer = None
        for key, val in all_selects.items():
            if key.lower() in label_text:
                answer = val
                break
        if not answer:
            continue
        try:
            parent = label.find_element(By.XPATH, "./..")
            ctrl = parent.find_element(By.CSS_SELECTOR, "[class*='select__control']")
            driver.execute_script("arguments[0].scrollIntoView(true);", ctrl)
            time.sleep(0.3)
            ctrl.click()
            time.sleep(0.5)
            for opt in driver.find_elements(By.CSS_SELECTOR, "[class*='select__option']"):
                if opt.text.strip().lower() == answer.lower():
                    opt.click()
                    print(f"  ✓ Selected '{answer}' for: {label_text[:50]}")
                    break
            time.sleep(0.3)
        except Exception:
            pass

    # Scroll to submit and click
    btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", btn)

    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║  Solve the reCAPTCHA in the browser window   ║")
    print("  ╚══════════════════════════════════════════════╝\n")

    # Wait for CAPTCHA solve → success page
    for i in range(150):  # 5 min
        time.sleep(2)
        page = driver.page_source.lower()
        if any(s in page for s in ["application has been submitted", "thank you for applying", "thanks for applying"]):
            print(f"  ✅ Applied: {title} @ {board}")
            return True
        if i and i % 15 == 0:
            print(f"  ⏳ Waiting... ({i*2}s)")

    print("  ❌ Timed out")
    return False


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 hybrid_greenhouse_apply.py <profile.yaml> <board> <job_id>")
        print("Example: python3 hybrid_greenhouse_apply.py profile.yaml discord 8200328002")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        profile = yaml.safe_load(f)

    board, job_id = sys.argv[2], sys.argv[3]

    # Load custom answers if provided
    custom_answers = {}
    if "--custom-answers" in sys.argv:
        idx = sys.argv.index("--custom-answers")
        with open(sys.argv[idx + 1]) as f:
            custom_answers = yaml.safe_load(f)

    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
        print(f"Set DISPLAY=:0 (DCV session)")

    opts = uc.ChromeOptions()
    opts.binary_location = CHROME_PATH
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=opts, headless=False)

    try:
        apply_to_job(board, job_id, profile, driver, custom_answers)
    except KeyboardInterrupt:
        print("\nAborted.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
