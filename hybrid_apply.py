#!/usr/bin/env python3
"""
Lever Auto-Apply — Hybrid mode (DCV).
Auto-fills the form, you solve the CAPTCHA in the DCV session.

Usage: python3 hybrid_apply.py profile.yaml <company> <posting_id>
"""

import os
import sys
import time

import yaml
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CHROME_PATH = "/tmp/opt/google/chrome/chrome"


def apply_to_job(company, posting_id, profile, driver):
    url = f"https://jobs.lever.co/{company}/{posting_id}/apply"
    print(f"\nOpening {url}")

    driver.get(url)
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "application-form")))

    # Grab title
    try:
        title = driver.find_element(By.CSS_SELECTOR, "h2").text
    except Exception:
        title = posting_id
    print(f"  Job: {title}")

    # Fill fields
    name = f"{profile['first_name']} {profile['last_name']}"
    for field, value in [
        ("name", name), ("email", profile["email"]),
        ("phone", profile.get("phone", "")),
        ("org", profile.get("current_company", "")),
        ("urls[LinkedIn]", profile.get("linkedin_url", "")),
        ("urls[GitHub]", profile.get("github_url", "")),
    ]:
        if not value:
            continue
        try:
            el = driver.find_element(By.NAME, field)
            el.clear()
            el.send_keys(value)
        except Exception:
            pass
    print("  ✓ Fields filled")

    # Resume
    driver.find_element(By.NAME, "resume").send_keys(profile["resume_path"])
    print("  ✓ Resume uploaded")
    time.sleep(3)

    # Submit → triggers CAPTCHA
    btn = driver.find_element(By.ID, "btn-submit")
    driver.execute_script("arguments[0].scrollIntoView(true);", btn)
    time.sleep(1)
    driver.execute_script("arguments[0].click();", btn)

    print("\n  ╔══════════════════════════════════════════╗")
    print("  ║  Solve the CAPTCHA in the browser window ║")
    print("  ╚══════════════════════════════════════════╝\n")

    # Wait for solve → /thanks redirect
    for i in range(150):  # 5 min
        time.sleep(2)
        if "/thanks" in driver.current_url:
            print(f"  ✅ Applied: {title} @ {company}")
            return True
        if i and i % 15 == 0:
            print(f"  ⏳ Waiting... ({i*2}s)")

    print("  ❌ Timed out")
    return False


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 hybrid_apply.py <profile.yaml> <company> <posting_id>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        profile = yaml.safe_load(f)

    company, posting_id = sys.argv[2], sys.argv[3]

    # Use DCV display if available, else fall back to Xvfb
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
        print(f"Set DISPLAY=:0 (DCV session)")

    opts = uc.ChromeOptions()
    opts.binary_location = CHROME_PATH
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    driver = uc.Chrome(options=opts, headless=False)

    try:
        apply_to_job(company, posting_id, profile, driver)
    except KeyboardInterrupt:
        print("\nAborted.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
