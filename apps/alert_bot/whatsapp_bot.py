"""WhatsApp alert bot for the Ha-Meem AI Surveillance system.

Architecture
────────────
AlertSender (abstract)
  └─ SeleniumAlertSender   — current implementation using WhatsApp Web + Selenium
  └─ WhatsAppAPIAlertSender — stub for the official WhatsApp Business Cloud API
                              (requires WHATSAPP_API_TOKEN + WHATSAPP_PHONE_ID env vars)

WhatsAppBot orchestrates:
  1. Polling thread  — calls GET /events/latest on the FastAPI server
  2. Sender queue    — bounded; events dropped gracefully on overflow
  3. Sender worker   — drains queue, calls alert_sender.send()
"""

import abc
import logging
import os
import sys
import tempfile
import threading
import time
from queue import Queue

import cv2
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/whatsapp_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

API_URL       = "http://127.0.0.1:8000/events/latest?limit=1"
POLL_INTERVAL = 2          # seconds between API polls
PHONE_NUMBER  = "8801834341444"
USER_DATA_DIR = os.path.abspath("whatsapp_session")
STEP_TIMEOUT  = 10
STEP_RETRIES  = 3

# ── Selenium selectors ─────────────────────────────────────────────────────────

SEL_CHAT_INPUT  = (By.XPATH, '//footer//div[@contenteditable="true"]')
SEL_LOGIN_READY = (By.XPATH, '//div[@contenteditable="true"]')
SEL_ATTACH_BTN  = (By.XPATH, '//button[@aria-label="Attach"]')
SEL_PHOTOS_MENU = (By.XPATH, '//span[contains(text(),"Photos")]')
SEL_FILE_INPUT  = (By.CSS_SELECTOR, 'input[type="file"][accept="image/*"]')
SEL_DIALOG      = (By.XPATH, '//div[@role="dialog"]')
SEL_CLOSE_BTN   = (By.XPATH, '//span[@data-icon="x"]')
SEL_SEND_BTN    = (By.XPATH, '//span[@data-icon="send"] | //div[@aria-label="Send"]')


# ── Abstract sender ────────────────────────────────────────────────────────────

class AlertSender(abc.ABC):
    """Abstract base for alert delivery backends."""

    @abc.abstractmethod
    def send(self, event: dict):
        """Send an alert for the given surveillance event."""


# ── Selenium implementation ────────────────────────────────────────────────────

def _compress_image(path: str):
    img = cv2.imread(path)
    if img is None:
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    cv2.imwrite(tmp.name, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return tmp.name


def _retry_clickable(driver, locator, label, timeout=STEP_TIMEOUT, retries=STEP_RETRIES):
    for attempt in range(1, retries + 1):
        try:
            return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
        except TimeoutException:
            log.warning(f"[{label}] timeout (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(1.5)
    return None


def _retry_present(driver, locator, label, timeout=STEP_TIMEOUT, retries=STEP_RETRIES):
    for attempt in range(1, retries + 1):
        try:
            return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))
        except TimeoutException:
            log.warning(f"[{label}] timeout (attempt {attempt}/{retries})")
            if attempt < retries:
                time.sleep(1.5)
    return None


def _dismiss_dialogs(driver):
    try:
        dialogs = [d for d in driver.find_elements(*SEL_DIALOG) if d.is_displayed()]
        if not dialogs:
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


class SeleniumAlertSender(AlertSender):
    """Delivers alerts via WhatsApp Web automation using Selenium Chrome."""

    def __init__(self, phone_number: str = PHONE_NUMBER):
        self.phone_number = phone_number
        self.driver = None
        self.wait = None
        self._start_browser()

    def _start_browser(self):
        opts = Options()
        opts.add_argument(f"--user-data-dir={USER_DATA_DIR}")
        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--remote-debugging-port=9222")
        opts.add_experimental_option("prefs", {
            "profile.default_content_setting_values.automatic_downloads": 1,
            "download.prompt_for_download": False,
            "safebrowsing.enabled": False,
        })
        log.info("Launching Chrome…")
        self.driver = webdriver.Chrome(options=opts)
        self.wait = WebDriverWait(self.driver, 60)

        self.driver.get("https://web.whatsapp.com/")
        try:
            self.wait.until(EC.presence_of_element_located(SEL_LOGIN_READY))
            log.info("WhatsApp Web login confirmed")
        except TimeoutException:
            self.driver.quit()
            raise RuntimeError("WhatsApp Web did not load in 60 s")

        self.driver.get(
            f"https://web.whatsapp.com/send?phone={self.phone_number}&text&app_absent=0"
        )
        try:
            self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))
            log.info("Chat ready")
        except TimeoutException:
            self.driver.quit()
            raise RuntimeError(f"Chat not found for {self.phone_number}")

    def _ensure_chat_focused(self):
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located(SEL_CHAT_INPUT)
            )
        except TimeoutException:
            log.warning("Chat input lost — re-opening…")
            self.driver.get(
                f"https://web.whatsapp.com/send?phone={self.phone_number}&text&app_absent=0"
            )
            self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))

    def _send_text(self, message: str):
        box = self.wait.until(EC.presence_of_element_located(SEL_CHAT_INPUT))
        lines = message.split("\n")
        for i, line in enumerate(lines):
            box.send_keys(line)
            if i < len(lines) - 1:
                box.send_keys(Keys.SHIFT + Keys.ENTER)
        box.send_keys(Keys.ENTER)

    @staticmethod
    def _build_message(event: dict) -> str:
        identity  = event.get("identity")
        camera    = event.get("camera_id", "unknown")
        ts        = event.get("timestamp", "")
        t         = ts[11:19] if len(ts) >= 19 else ts
        if identity:
            return f"Entry Detected\n\nName: {identity}\nCamera: {camera}\nTime: {t}\nSnapshot attached."
        return f"Unknown person detected\n\nCamera: {camera}\nTime: {t}\nSnapshot attached."

    def send(self, event: dict):
        _dismiss_dialogs(self.driver)
        self._ensure_chat_focused()

        message  = self._build_message(event)
        snapshot = event.get("snapshot")

        self._send_text(message)

        if not snapshot or not os.path.exists(snapshot):
            log.info("No snapshot — text-only alert sent")
            return

        img_path = _compress_image(snapshot)
        if img_path is None:
            log.warning("Image compression failed — text already sent")
            return

        abs_path = os.path.abspath(img_path)
        try:
            attach_btn = _retry_clickable(self.driver, SEL_ATTACH_BTN, "attach")
            if attach_btn is None:
                return
            self.driver.execute_script("arguments[0].click();", attach_btn)
            time.sleep(1.2)

            photos = _retry_clickable(self.driver, SEL_PHOTOS_MENU, "photos")
            if photos is None:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                return
            self.driver.execute_script("arguments[0].click();", photos)
            time.sleep(1.5)

            file_input = _retry_present(self.driver, SEL_FILE_INPUT, "file_input")
            if file_input is None:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                return

            self.driver.execute_script(
                "arguments[0].style.display='block';"
                "arguments[0].style.visibility='visible';"
                "arguments[0].style.opacity='1';",
                file_input,
            )
            time.sleep(0.3)
            file_input.send_keys(abs_path)
            time.sleep(5.0)

            send_btn = _retry_clickable(self.driver, SEL_SEND_BTN, "send")
            if send_btn:
                self.driver.execute_script("arguments[0].click();", send_btn)
                log.info("Image alert sent")
            else:
                self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ENTER)

            time.sleep(3.0)

        except Exception as e:
            log.exception(f"Image send error: {e}")
        finally:
            if img_path and os.path.exists(img_path):
                try:
                    os.unlink(img_path)
                except Exception:
                    pass


# ── Official API stub ──────────────────────────────────────────────────────────

class WhatsAppAPIAlertSender(AlertSender):
    """Alert sender using the WhatsApp Business Cloud API.

    Set environment variables:
      WHATSAPP_API_TOKEN  — Bearer token from Meta Developer Console
      WHATSAPP_PHONE_ID   — Phone number ID (not the phone number itself)
      WHATSAPP_RECIPIENT  — Recipient phone number in E.164 format
    """

    def __init__(self):
        self.token     = os.environ.get("WHATSAPP_API_TOKEN", "")
        self.phone_id  = os.environ.get("WHATSAPP_PHONE_ID", "")
        self.recipient = os.environ.get("WHATSAPP_RECIPIENT", PHONE_NUMBER)
        if not self.token or not self.phone_id:
            raise EnvironmentError(
                "WHATSAPP_API_TOKEN and WHATSAPP_PHONE_ID must be set "
                "to use WhatsAppAPIAlertSender."
            )

    def send(self, event: dict):
        identity  = event.get("identity")
        camera    = event.get("camera_id", "unknown")
        ts        = event.get("timestamp", "")[:19]
        body = (
            f"*Entry Detected*\nName: {identity}\nCamera: {camera}\nTime: {ts}"
            if identity
            else f"*Unknown Person*\nCamera: {camera}\nTime: {ts}"
        )
        url     = f"https://graph.facebook.com/v19.0/{self.phone_id}/messages"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": self.recipient,
            "type": "text",
            "text": {"body": body},
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=10)
            r.raise_for_status()
            log.info(f"WhatsApp API alert sent (status {r.status_code})")
        except Exception as e:
            log.error(f"WhatsApp API send failed: {e}")


# ── Bot orchestrator ───────────────────────────────────────────────────────────

class WhatsAppBot:
    """Polls the surveillance API and dispatches alerts via an AlertSender."""

    def __init__(self, sender: AlertSender):
        os.makedirs("logs", exist_ok=True)
        self.sender = sender
        self.processed_ids: set = set()
        self.last_timestamp: str = ""
        self.queue: Queue = Queue(maxsize=3)

        worker = threading.Thread(target=self._sender_worker, daemon=True)
        worker.start()
        log.info("WhatsAppBot started — sender thread running")

    def _sender_worker(self):
        while True:
            event = self.queue.get()
            try:
                self.sender.send(event)
            except Exception as e:
                log.error(f"Sender worker error: {e}")
            finally:
                self.queue.task_done()

    def poll(self):
        log.info("Polling started")
        while True:
            try:
                r = requests.get(API_URL, timeout=5)
                if r.status_code == 200:
                    data  = r.json()
                    event = data[-1] if isinstance(data, list) and data else None
                    if event:
                        ts       = event.get("timestamp", "")
                        event_id = f"{ts}_{event.get('track_id')}"
                        if ts != self.last_timestamp and event_id not in self.processed_ids:
                            self.last_timestamp = ts
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


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sender = SeleniumAlertSender()
    bot    = WhatsAppBot(sender)
    bot.poll()
