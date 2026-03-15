import os
import time
import cv2
import requests
import tempfile
import threading
from queue import Queue

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ---------------- CONFIG ----------------

API_URL = "http://127.0.0.1:8000/events/latest?limit=1"

POLL_INTERVAL = 2

PHONE_NUMBER = "8801834341444"

USER_DATA_DIR = os.path.abspath("whatsapp_session")

# ----------------------------------------


def compress_image(path):
    img = cv2.imread(path)

    if img is None:
        return None

    tmp = tempfile.NamedTemporaryFile(
        suffix=".jpg",
        delete=False
    )

    cv2.imwrite(tmp.name, img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    return tmp.name


class WhatsAppBot:

    def __init__(self):

        self.processed_ids = set()

        self.last_timestamp = None

        self.queue = Queue(maxsize=3)

        self.driver = None
        self.wait = None

        self._start_browser()

        sender = threading.Thread(target=self._sender_worker)
        sender.daemon = True
        sender.start()


# ---------------- BROWSER ----------------

    def _start_browser(self):

        chrome_options = Options()
        chrome_options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-notifications")
        
        # Windows stability flags
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--remote-debugging-port=9222")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 60)

        print("Opening WhatsApp Web")

        self.driver.get("https://web.whatsapp.com/")

        self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"]')
            )
        )

        print("Login confirmed")

        chat_url = f"https://web.whatsapp.com/send?phone={PHONE_NUMBER}&text&app_absent=0"

        self.driver.get(chat_url)

        self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//footer//div[@contenteditable="true"]')
            )
        )

        print("Chat ready")


# ---------------- MESSAGE ----------------

    def _build_message(self, event):

        identity = event["identity"]
        camera = event["camera_id"]
        timestamp = event["timestamp"]

        if identity:
            return (
                "Entry Detected\n\n"
                f"Name: {identity}\n"
                f"Camera: {camera}\n"
                f"Time: {timestamp[11:19]}\n"
                "Snapshot attached."
            )

        else:
            return (
                "Unknown person detected\n\n"
                f"Camera: {camera}\n"
                f"Time: {timestamp[11:19]}\n"
                "Snapshot attached."
            )


# ---------------- SEND ALERT ----------------

    def _send_alert(self, event):

        # ensure no previous dialog open
        dialogs = self.driver.find_elements(By.XPATH, '//div[@role="dialog"]')

        if dialogs:
            print("Closing stuck media dialog")

            try:
                close_btn = dialogs[0].find_element(By.XPATH, './/span[@data-icon="x"]')
                self.driver.execute_script("arguments[0].click();", close_btn)
                time.sleep(1)

            except:
                # fallback: press ESC
                from selenium.webdriver.common.keys import Keys
                self.driver.switch_to.active_element.send_keys(Keys.ESCAPE)
                time.sleep(1)

        snapshot = event.get("snapshot")
        message = self._build_message(event)

        if snapshot and os.path.exists(snapshot):
            img_path = compress_image(snapshot)
            if img_path is None: return

            print(f"Uploading snapshot: {img_path}")

            try:
                # 1. Target the 'Photos & Videos' uploader specifically
                # Stickers often use 'image/webp'. Standard photos use image/*
                uploader = self.wait.until(
                    EC.presence_of_element_located((By.XPATH, '//input[@type="file" and contains(@accept, "image/*")]'))
                )
                uploader.send_keys(os.path.abspath(img_path))

                # 2. Wait for the UI to transition (Preview screen)
                print("Waiting for preview state...")
                time.sleep(3) # Give WhatsApp enough time to render the full preview DOM

                # 3. Locate Caption Field (strictly inside dialog)
                print("Detecting caption area inside dialog...")
                caption = None
                caption_selectors = [
                    '//div[@role="dialog"]//div[@contenteditable="true"][@data-tab="10"]',
                    '//div[@role="dialog"]//div[@aria-placeholder="Add a caption"]',
                    '//div[@role="dialog"]//div[@role="textbox"]',
                    '//div[@role="dialog"]//div[@contenteditable="true"]'
                ]
                for xpath in caption_selectors:
                    els = self.driver.find_elements(By.XPATH, xpath)
                    for el in els:
                        if el.is_displayed():
                            caption = el
                            print(f"Caption found via: {xpath}")
                            break
                    if caption: break

                if caption:
                    # Use JS to focus/click to avoid interception
                    self.driver.execute_script("arguments[0].focus();", caption)
                    self.driver.execute_script("arguments[0].click();", caption)
                    caption.clear()
                    
                    from selenium.webdriver.common.keys import Keys
                    # Use Shift+Enter for newlines to keep formatting in one bubble
                    for char in message:
                        if char == '\n':
                            caption.send_keys(Keys.SHIFT + Keys.ENTER)
                        else:
                            caption.send_keys(char)
                    print("Caption entered.")
                else:
                    print("Could not find caption box - identity data will be sent separately.")

                # 4. Find and Click Send Button (strictly inside dialog)
                print("Detecting send button inside dialog...")
                send_btn = None
                send_selectors = [
                    '//div[@role="dialog"]//span[@data-icon="send"]/ancestor::button',
                    '//div[@role="dialog"]//div[@role="button"]//span[@data-icon="send"]',
                    '//div[@role="dialog"]//button[@type="submit"]',
                    '//div[@role="dialog"]//div[@aria-label="Send"]'
                ]
                for xpath in send_selectors:
                    els = self.driver.find_elements(By.XPATH, xpath)
                    for el in els:
                        if el.is_displayed():
                            send_btn = el
                            print(f"Send button found via: {xpath}")
                            break
                    if send_btn: break

                if send_btn:
                    self.driver.execute_script("arguments[0].click();", send_btn)
                    print("Alert sent.")
                elif caption:
                    print("Send button missing - forcing Enter on caption.")
                    caption.send_keys(Keys.ENTER)
                else:
                    raise Exception("UI stuck in preview - no caption or send button detected.")

                # 5. Wait for preview to close
                time.sleep(2)
                dialogs = self.driver.find_elements(By.XPATH, '//div[@role="dialog"]')
                if dialogs:
                    print("Closing persistent preview...")
                    self.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)

            except Exception as e:
                print(f"Failed to send media alert: {e}")
                
                # RECOVERY: If the image failed or got stuck, just send the text alert
                print("Attempting text-only fallback...")
                try:
                    from selenium.webdriver.common.keys import Keys
                    body = self.driver.find_element(By.TAG_NAME, "body")
                    body.send_keys(Keys.ESCAPE) # Clear any stuck dialogs
                    time.sleep(1)
                    
                    box = self.wait.until(EC.presence_of_element_located((By.XPATH, '//footer//div[@contenteditable="true"]')))
                    box.send_keys(message + "\n")
                    print("Text fallback sent.")
                except Exception as ex:
                    print(f"Text fallback also failed: {ex}")
                raise e

    
        else:
    
            print("Snapshot missing")
    
            box = self.wait.until(
                EC.presence_of_element_located(
                    (By.XPATH, '//footer//div[@contenteditable="true"]')
                )
            )
    
            box.send_keys(message + "\n")


# ---------------- SENDER THREAD ----------------

    def _sender_worker(self):

        while True:

            event = self.queue.get()

            try:
                self._send_alert(event)

            except Exception as e:
                err_msg = str(e)
                if "Stacktrace" in err_msg or "Symbols not available" in err_msg:
                    print("Send error: WhatsApp UI changed or interactive timeout.")
                else:
                    print(f"Send error: {err_msg}")

            self.queue.task_done()


# ---------------- POLLING ----------------

    def poll(self):

        print("Polling events")

        while True:

            try:

                r = requests.get(API_URL, timeout=5)

                if r.status_code != 200:
                    time.sleep(POLL_INTERVAL)
                    continue

                data = r.json()

                # backend may return list or object
                if isinstance(data, list):
                    if not data:
                        time.sleep(POLL_INTERVAL)
                        continue
                    event = data[-1]
                else:
                    event = data

                event_time = event["timestamp"]

                if event_time == self.last_timestamp:
                    time.sleep(POLL_INTERVAL)
                    continue

                self.last_timestamp = event_time

                event_id = f"{event['timestamp']}_{event['track_id']}"

                if event_id not in self.processed_ids:

                    self.processed_ids.add(event_id)

                    if not self.queue.full():
                        self.queue.put(event)

            except Exception as e:

                print("Polling error:", e)

            time.sleep(POLL_INTERVAL)


# ---------------- MAIN ----------------

if __name__ == "__main__":

    bot = WhatsAppBot()

    bot.poll()