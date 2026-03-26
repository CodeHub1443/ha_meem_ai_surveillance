import os
import sys
import time
import random
import logging
import tempfile
import threading
from queue import Queue

import cv2
import pyautogui
import requests

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, WebDriverException

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/whatsapp_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

API_URL         = "http://127.0.0.1:8000/events/latest?limit=1"
POLL_INTERVAL   = 2          # seconds between polls
PHONE_NUMBER    = "8801834341444"
USER_DATA_DIR   = os.path.abspath("whatsapp_session")

# Per-step Selenium timeouts / retry counts
STEP_TIMEOUT    = 10         # seconds per wait.until()
STEP_RETRIES    = 3          # attempts per step before giving up that step

# ── Selectors (one place to update when WA Web changes) ──────────────────────

SEL_CHAT_INPUT   = (By.XPATH, '//footer//div[@contenteditable="true"]')
SEL_LOGIN_READY  = (By.XPATH, '//div[@contenteditable="true"]')
SEL_ATTACH_BTN   = (By.XPATH, '//button[@aria-label="Attach"]')
SEL_PHOTOS_MENU  = (By.XPATH, '//span[contains(text(),"Photos")]')
SEL_FILE_INPUT   = (By.CSS_SELECTOR, 'input[type="file"][accept="image/*"]')
SEL_DIALOG       = (By.XPATH, '//div[@role="dialog"]')
SEL_CLOSE_BTN    = (By.XPATH, '//span[@data-icon="x"]')
SEL_SEND_BTN     = (By.XPATH,
    '//span[@data-icon="send"] | //div[@aria-label="Send"]'
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def compress_image(path: str) -> str | None:
    img = cv2.imread(path)
    if img is None:
        log.warning(f"cv2 could not read image: {path}")
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    cv2.imwrite(tmp.name, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return tmp.name


def _retry_clickable(driver, locator, label: str,
                     timeout=STEP_TIMEOUT, retries=STEP_RETRIES):
    """Wait for a clickable element, retrying on TimeoutException."""
    for attempt in range(1, retries + 1):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable(locator)
            )
            log.debug(f"[{label}] clickable (attempt {attempt})")
            return el
        except TimeoutException:
            log.warning(f"[{label}] timeout (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(1.5)
    return None   # caller decides what to do


def _retry_present(driver, locator, label: str,
                   timeout=STEP_TIMEOUT, retries=STEP_RETRIES):
    """Wait for element presence, retrying on TimeoutException."""
    for attempt in range(1, retries + 1):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            log.debug(f"[{label}] present (attempt {attempt})")
            return el
        except TimeoutException:
            log.warning(f"[{label}] timeout (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(1.5)
    return None


def _find_caption(driver, timeout=6):
    for xp in CAPTION_XPATHS:
        try:
            els = WebDriverWait(driver, timeout).until(
                EC.presence_of_all_elements_located((By.XPATH, xp))
            )
            for el in els:
                if el.is_displayed():
                    log.debug(f"Caption found: {xp}")
                    return el
        except TimeoutException:
            continue
        except Exception as e:
            log.debug(f"Caption XPath error: {e}")
    return None


def _type_caption(driver, el, message: str):
    driver.execute_script("arguments[0].focus(); arguments[0].click();", el)
    time.sleep(0.3)
    # Select all and delete instead of clear() — more reliable on contenteditable
    el.send_keys(Keys.CONTROL + "a")
    el.send_keys(Keys.DELETE)
    time.sleep(0.2)
    lines = message.split("\n")
    for i, line in enumerate(lines):
        el.send_keys(line)
        if i < len(lines) - 1:
            el.send_keys(Keys.SHIFT + Keys.ENTER)
    time.sleep(0.4)
    log.debug("Caption typed")


def _dismiss_dialogs(driver):
    try:
        dialogs = driver.find_elements(*SEL_DIALOG)
        if not dialogs:
            return
        visible = [d for d in dialogs if d.is_displayed()]
        if not visible:
            return
        log.info("Dismissing stuck dialog…")
        for btn in driver.find_elements(*SEL_CLOSE_BTN):
            if btn.is_displayed():
                driver.execute_script("arguments[0].click();", btn)
                time.sleep(0.8)
                return
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        time.sleep(0.8)
    except Exception as e:
        log.debug(f"Dialog dismiss skipped: {e}")


# ── Bot ───────────────────────────────────────────────────────────────────────

class WhatsAppBot:

    def __init__(self):
        os.makedirs("logs", exist_ok=True)

        self.processed_ids: set = set()
        self.last_timestamp: str | None = None
        self.queue: Queue = Queue(maxsize=3)
        self.driver = None
        self.wait = None

        try:
            self._start_browser()
        except Exception as e:
            log.critical(f"Browser startup failed: {e}", exc_info=True)
            raise SystemExit(1)

        sender = threading.Thread(target=self._sender_worker, daemon=True)
        sender.start()
        log.info("WhatsAppBot initialised — sender thread running")

    # ── Browser ───────────────────────────────────────────────────────────────

    def _start_browser(self):
        opts = Options()
        opts.add_argument(f"--user-data-dir={USER_DATA_DIR}")
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--remote-debugging-port=9222")
        # Suppress the native file picker dialog that flashes on Windows
        # when send_keys injects a path into a hidden file input
        opts.add_argument("--disable-file-system")
        opts.add_experimental_option("prefs", {
            "profile.default_content_setting_values.automatic_downloads": 1,
            "download.prompt_for_download": False,
            "safebrowsing.enabled": False,
        })

        log.info("Launching Chrome…")
        self.driver = webdriver.Chrome(options=opts)
        self.wait   = WebDriverWait(self.driver, 60)

        log.info("Opening WhatsApp Web — scan QR if needed…")
        self.driver.get("https://web.whatsapp.com/")

        try:
            self.wait.until(EC.presence_of_element_located(SEL_LOGIN_READY))
            log.info("Login confirmed")
        except TimeoutException:
            log.critical(
                "WhatsApp Web did not load in 60 s. "
                "Check: (1) internet, (2) QR scanned, (3) correct Chrome profile."
            )
            self.driver.quit()
            raise

        chat_url = (
            f"https://web.whatsapp.com/send?phone={PHONE_NUMBER}"
            "&text&app_absent=0"
        )
        self.driver.get(chat_url)

        try:
            self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))
            log.info("Chat ready ✓")
        except TimeoutException:
            log.critical(
                f"Chat input not found for {PHONE_NUMBER}. "
                "Is the number correct and saved in contacts?"
            )
            self.driver.quit()
            raise

    # ── Message builder ───────────────────────────────────────────────────────

    def _build_message(self, event: dict) -> str:
        identity  = event.get("identity")
        camera    = event.get("camera_id", "unknown")
        timestamp = event.get("timestamp", "")
        t = timestamp[11:19] if len(timestamp) >= 19 else timestamp

        if identity:
            return (
                "Entry Detected\n\n"
                f"Name: {identity}\n"
                f"Camera: {camera}\n"
                f"Time: {t}\n"
                "Snapshot attached."
            )
        return (
            "Unknown person detected\n\n"
            f"Camera: {camera}\n"
            f"Time: {t}\n"
            "Snapshot attached."
        )

    # ── Chat focus guard ──────────────────────────────────────────────────────

    def _ensure_chat_focused(self):
        """Re-navigate to the chat if the footer input is gone."""
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(SEL_CHAT_INPUT)
            )
        except TimeoutException:
            log.warning("Chat input lost — re-opening chat…")
            chat_url = (
                f"https://web.whatsapp.com/send?phone={PHONE_NUMBER}"
                "&text&app_absent=0"
            )
            self.driver.get(chat_url)
            self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))
            log.info("Chat re-focused")

    # ── Text-only fallback ────────────────────────────────────────────────────

    def _send_text_only(self, message: str):
        try:
            box = self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))
            lines = message.split("\n")
            for i, line in enumerate(lines):
                box.send_keys(line)
                if i < len(lines) - 1:
                    box.send_keys(Keys.SHIFT + Keys.ENTER)
            box.send_keys(Keys.ENTER)
            log.info("Text-only alert sent")
        except Exception as e:
            log.error(f"Text-only fallback failed: {e}")

    # ── Main send ─────────────────────────────────────────────────────────────

    def _send_alert(self, event: dict):
        _dismiss_dialogs(self.driver)
        self._ensure_chat_focused()

        message   = self._build_message(event)
        snapshot  = event.get("snapshot")
        img_path  = None

        # ── Step 1: Always send text first ───────────────────────────────────
        self._send_text_only(message)

        # ── No snapshot → done ────────────────────────────────────────────────
        if not snapshot or not os.path.exists(snapshot):
            log.info("No snapshot — text only sent")
            return

        # ── Step 2: Compress image ────────────────────────────────────────────
        img_path = compress_image(snapshot)
        if img_path is None:
            log.warning("Compression failed — text already sent, skipping image")
            return

        abs_path = os.path.abspath(img_path)
        log.info(f"Attaching image: {abs_path}")

        try:
            # ── Step 3: Attach button ─────────────────────────────────────────
            attach_btn = _retry_clickable(self.driver, SEL_ATTACH_BTN, "attach_btn")
            if attach_btn is None:
                log.error("Attach button not found — text already sent, skipping image")
                return
            self.driver.execute_script("arguments[0].click();", attach_btn)
            time.sleep(1.0 + random.uniform(0, 0.4))

            # ── Step 4: Photos & Videos menu ─────────────────────────────────
            photos = _retry_clickable(self.driver, SEL_PHOTOS_MENU, "photos_menu")
            if photos is None:
                log.error("Photos menu not found — skipping image")
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                return
            self.driver.execute_script("arguments[0].click();", photos)
            time.sleep(1.2 + random.uniform(0, 0.5))

            # ── Step 5: File input ────────────────────────────────────────────
            file_input = _retry_present(self.driver, SEL_FILE_INPUT, "file_input")
            if file_input is None:
                log.error("File input not found — skipping image")
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                return

            # Make the hidden input interactable before injecting the path.
            # Without this, Chrome opens the native file dialog on Windows.
            self.driver.execute_script("""
                arguments[0].style.display = 'block';
                arguments[0].style.visibility = 'visible';
                arguments[0].style.opacity = '1';
            """, file_input)
            time.sleep(0.3)
            file_input.send_keys(abs_path)

            # On Windows, Chrome briefly flashes a native file picker even
            # when the path is injected successfully. Dismiss it immediately.
            time.sleep(0.5)   # give the dialog time to appear
            pyautogui.press("escape")
            log.debug("File dialog dismissed")

            # Longer wait — lets WhatsApp fully load the photo preview
            time.sleep(4.5 + random.uniform(0.5, 1.5))

            # ── Step 6: Send button ───────────────────────────────────────────
            send_btn = _retry_clickable(self.driver, SEL_SEND_BTN, "send_btn")
            if send_btn:
                self.driver.execute_script("arguments[0].click();", send_btn)
                log.info("Image sent ✓")
            else:
                log.warning("Send button not found → pressing Enter")
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ENTER)

            time.sleep(3 + random.uniform(0, 1))

        except Exception as e:
            log.exception(f"Unhandled error sending image: {e}")

        finally:
            if img_path and os.path.exists(img_path):
                try:
                    os.unlink(img_path)
                except Exception as e:
                    log.debug(f"Temp file cleanup failed: {e}")

    # ── Sender thread ─────────────────────────────────────────────────────────

    def _sender_worker(self):
        while True:
            event = self.queue.get()
            try:
                self._send_alert(event)
            except Exception as e:
                log.error(f"Sender worker error: {e}")
            finally:
                self.queue.task_done()

    # ── Polling ───────────────────────────────────────────────────────────────

    def poll(self):
        log.info("Polling started")
        while True:
            try:
                r = requests.get(API_URL, timeout=5)
                if r.status_code != 200:
                    time.sleep(POLL_INTERVAL)
                    continue

                data  = r.json()
                event = data[-1] if isinstance(data, list) else data

                if not event:
                    time.sleep(POLL_INTERVAL)
                    continue

                event_time = event.get("timestamp")
                if event_time == self.last_timestamp:
                    time.sleep(POLL_INTERVAL)
                    continue

                self.last_timestamp = event_time
                event_id = f"{event.get('timestamp')}_{event.get('track_id')}"

                if event_id not in self.processed_ids:
                    self.processed_ids.add(event_id)
                    if not self.queue.full():
                        self.queue.put(event)
                        log.info(f"Event queued: {event_id}")
                    else:
                        log.warning("Queue full — event dropped")

            except requests.exceptions.ConnectionError:
                log.warning("API unreachable — is the FastAPI server running?")
            except Exception as e:
                log.error(f"Polling error: {e}")

            time.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot = WhatsAppBot()
    bot.poll()