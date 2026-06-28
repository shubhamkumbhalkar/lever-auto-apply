#!/usr/bin/env python3
"""Interactive application helper — opens visible browser for CAPTCHA solving.

Fills the form automatically, then waits for you to solve CAPTCHA and confirm.
Run this while connected to DCV.
"""

import os
import sys
import time
import json
import yaml
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

os.environ["DISPLAY"] = ":0"

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


def apply_openai_ashby(config: dict, cover_letter: str, job_url: str):
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")

    logger.info("Opening Chrome (visible in DCV)...")
    driver = uc.Chrome(options=opts, headless=False)

    try:
        app_url = job_url.rstrip("/") + "/application"
        logger.info("Loading %s", app_url)
        driver.get(app_url)
        time.sleep(8)

        # Fill fields
        driver.find_element(By.CSS_SELECTOR, "input[name='_systemfield_name']").send_keys(
            f"{config['first_name']} {config['last_name']}")
        logger.info("✓ Name")

        driver.find_element(By.CSS_SELECTOR, "input[name='_systemfield_email']").send_keys(config['email'])
        logger.info("✓ Email")

        # Resume
        for fi in driver.find_elements(By.CSS_SELECTOR, "input[type='file']"):
            try:
                fi.send_keys(config['resume_path'])
                logger.info("✓ Resume uploaded")
                time.sleep(3)
                break
            except Exception:
                continue

        # Phone
        phone_fields = driver.find_elements(By.CSS_SELECTOR, "input[type='tel']")
        if phone_fields:
            phone_fields[0].send_keys(config['phone'])
            logger.info("✓ Phone")

        # Location
        loc_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder='Start typing...']")
        if loc_inputs:
            loc_inputs[0].send_keys("Chicago, Illinois")
            time.sleep(2)
            options = driver.find_elements(By.CSS_SELECTOR, "[role='option']")
            if options:
                options[0].click()
            else:
                loc_inputs[0].send_keys(Keys.RETURN)
            logger.info("✓ Location")
        time.sleep(1)

        # Start date
        date_inputs = driver.find_elements(By.CSS_SELECTOR, "input[placeholder='Pick date...']")
        if date_inputs:
            date_inputs[0].click()
            time.sleep(0.5)
            date_inputs[0].send_keys("07/15/2026")
            date_inputs[0].send_keys(Keys.ESCAPE)
            logger.info("✓ Start date")
        time.sleep(1)

        # Work authorization = Yes
        auth_cbs = driver.find_elements(By.CSS_SELECTOR,
            "input[name='bed95633-1b6e-4cd0-9eaf-c5a9f75ac35d']")
        if auth_cbs and not auth_cbs[0].is_selected():
            driver.execute_script("arguments[0].click();", auth_cbs[0])
        logger.info("✓ Work auth: Yes")

        # In-office 3 days = Yes
        office_cbs = driver.find_elements(By.CSS_SELECTOR,
            "input[name='d33e2a8f-3742-4e5e-b91c-b7607d3cdf63']")
        if office_cbs and not office_cbs[0].is_selected():
            driver.execute_script("arguments[0].click();", office_cbs[0])
        logger.info("✓ In-office: Yes")

        # Cover letter
        textareas = driver.find_elements(By.TAG_NAME, "textarea")
        if textareas:
            textareas[0].send_keys(cover_letter)
            logger.info("✓ Cover letter")

        # Agreements
        for name in ["a90e16d2-baaf-4c31-b3e5-70b53f261040", "7fe82de7-a1d7-4d8a-95a5-e5cc9adc84ea"]:
            for cb in driver.find_elements(By.CSS_SELECTOR, f"input[name='{name}']"):
                if not cb.is_selected():
                    driver.execute_script("arguments[0].click();", cb)
        logger.info("✓ Agreements")

        # Scroll to bottom
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        print("\n" + "="*60)
        print("  ✅ FORM FILLED! Now in your DCV session:")
        print("  1. Solve the CAPTCHA (click 'I'm not a robot')")
        print("  2. Click 'Submit Application'")
        print("  3. Come back here and press Enter when done")
        print("="*60 + "\n")

        # Keep browser open for 5 minutes for manual CAPTCHA solving
        logger.info("Browser will stay open for 5 minutes. Solve CAPTCHA and submit.")
        time.sleep(300)

        # Check if it worked
        page = driver.page_source.lower()
        if any(s in page for s in ["thank you", "submitted", "received"]):
            print("\n✅ Application confirmed!")
        else:
            print("\n📋 Check the browser to confirm submission status.")

    finally:
        logger.info("Closing browser.")
        driver.quit()


if __name__ == "__main__":
    with open("profile.yaml") as f:
        config = yaml.safe_load(f)
    with open("/tmp/openai_cover_letter.txt") as f:
        cover_letter = f.read()

    job_url = "https://jobs.ashbyhq.com/openai/73e56947-5d8b-414d-a0ac-9dc9b04e2406"
    apply_openai_ashby(config, cover_letter, job_url)
