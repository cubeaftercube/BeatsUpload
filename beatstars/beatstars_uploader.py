"""
BeatStars Uploader Module
Automates uploading beats to BeatStars.com via Selenium.
Refactored from the cloned beatstars-upload project to work with
database track records instead of filesystem-based beat numbering.
"""

import os
import time

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from file_processing import convert_key_to_beatstars

load_dotenv()

# Mapping from internal key format to BeatStars display format
KEY_DICT = {
    "A-Flat-Minor": "A-flat minor",
    "A-Flat-Major": "A-flat major",
    "A-Minor": "A minor",
    "A-Major": "A major",
    "A-Sharp-Minor": "A-sharp minor",
    "A-Sharp-Major": "A-sharp major",
    "B-Flat-Minor": "B-flat minor",
    "B-Flat-Major": "B-flat major",
    "B-Minor": "B minor",
    "B-Major": "B major",
    "C-Flat-Major": "C-flat major",
    "C-Minor": "C minor",
    "C-Major": "C major",
    "C-Sharp-Minor": "C-sharp minor",
    "C-Sharp-Major": "C-sharp major",
    "D-Flat-Major": "D-flat major",
    "D-Minor": "D minor",
    "D-Major": "D major",
    "D-Sharp-Minor": "D-sharp minor",
    "E-Flat-Major": "E-flat major",
    "E-Minor": "E minor",
    "E-Major": "E major",
    "F-Minor": "F minor",
    "F-Major": "F major",
    "F-Sharp-Minor": "F-sharp minor",
    "F-Sharp-Major": "F-sharp major",
    "G-Flat-Major": "G-flat major",
    "G-Minor": "G minor",
    "G-Major": "G major",
    "G-Sharp-Minor": "G-sharp minor",
}


def crop_cover_square(image_path: str, output_path: str, size: int = 540) -> str:
    """Center-crop a cover image to a square and save as JPEG.

    BeatStars expects a square cover image. This takes any aspect ratio
    image, center-crops it to a square, and resizes to `size`×`size`.

    Args:
        image_path: Path to the source image.
        output_path: Where to save the cropped JPEG.
        size: Output width and height in pixels (default 540).

    Returns:
        The output_path on success.

    Raises:
        ImportError: If Pillow is not installed.
        Exception: If the image cannot be opened or processed.
    """
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size

    # Center crop to square
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    right = left + min_dim
    bottom = top + min_dim

    cropped = img.crop((left, top, right, bottom))
    cropped = cropped.resize((size, size), Image.LANCZOS)
    cropped.save(output_path, "JPEG")
    return output_path


def upload_to_beatstars(
    track: dict,
    tags: list[str],
    key: str | None = None,
    bpm: int | None = None,
    wav_path: str | None = None,
) -> dict:
    """Upload a track to BeatStars via Selenium browser automation.

    Opens a visible Chrome window, logs into BeatStars, fills in the
    track metadata form, uploads the MP3 (and optionally WAV + cover),
    and leaves the browser open for manual review and publish-date
    selection.

    Args:
        track: Track dict from the database. Must contain at least:
               ``file_path`` (path to MP3), ``title``, ``artist``,
               and optionally ``cover_path``.
        tags: List of up to 3 artist tags (e.g. ["Drake", "Future"]).
        key: Optional musical key in internal format (e.g. "C-Minor").
             Must be a key from ``KEY_DICT``.
        bpm: Optional tempo in BPM.
        wav_path: Optional path to a WAV version of the track.
                  If omitted, only the MP3 is uploaded.

    Returns:
        A dict with:
        - ``success`` (bool)
        - ``error`` (str | None) — description on failure
        - ``message`` (str | None) — info text on success
    """
    mp3_path = track.get("file_path")
    cover_path = track.get("cover_path")
    title = track.get("title") or "Untitled"

    # Fallback to track dict values if not explicitly provided
    if bpm is None:
        bpm = track.get("bpm")
    if key is None:
        key = track.get("key")

    # --- Validation ---
    if not mp3_path or not os.path.exists(mp3_path):
        return {
            "success": False,
            "error": f"MP3 file not found: {mp3_path}",
            "message": None,
        }

    username = os.getenv("BEATSTARS_USERNAME")
    password = os.getenv("BEATSTARS_PASSWORD")

    if not username or not password:
        return {
            "success": False,
            "error": (
                "BeatStars credentials not configured. "
                "Set BEATSTARS_USERNAME and BEATSTARS_PASSWORD in .env"
            ),
            "message": None,
        }

    # --- Prepare cropped cover ---
    cropped_cover = None
    if cover_path and os.path.exists(cover_path):
        try:
            cropped_cover = os.path.join(
                os.path.dirname(cover_path) or ".",
                "_bs_cropped_cover.jpg",
            )
            crop_cover_square(cover_path, cropped_cover)
        except Exception as e:
            print(f"[BeatStars] Warning: could not crop cover: {e}")

    # --- Build title ---
    beat_title = f"{title} | {tags[0]} Type Beat" if tags else title

    # --- Setup Chrome (visible, not headless) ---
    chrome_options = Options()
    chrome_options.add_experimental_option("detach", True)

    driver = webdriver.Chrome(
        ChromeDriverManager().install(), options=chrome_options
    )
    driver.maximize_window()

    try:
        # ============================================================
        # 1. LOGIN
        # ============================================================
        driver.get("https://www.beatstars.com/dashboard")

        # Email step
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#oath-email"))
        )
        elem.send_keys(username)
        elem.send_keys(Keys.RETURN)

        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#btn-submit-oath")
            )
        )
        elem.click()

        # Password step
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#userPassword")
            )
        )
        elem.send_keys(password)
        elem.send_keys(Keys.RETURN)

        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#btn-submit-oath")
            )
        )
        elem.click()

        # ============================================================
        # 2. ACCEPT COOKIES & CLOSE POPUPS
        # ============================================================
        try:
            elem = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#onetrust-accept-btn-handler")
                )
            )
            elem.click()
        except Exception:
            time.sleep(5)
        try:
            elem = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "#onetrust-accept-btn-handler")
                )
            )
            elem.click()
        except Exception:
            pass

        # Close welcome popup/dialog
        try:
            elem = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (
                        By.XPATH,
                        '//*[@id="mat-dialog-0"]/bs-responsive-dialog-feature-template'
                        '/bs-container-grid/div/div[1]/button',
                    )
                )
            )
            elem.click()
        except Exception:
            pass

        # ============================================================
        # 3. NAVIGATE TO UPLOAD FORM
        # ============================================================
        # Click "Upload" button in top nav
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#app-body > mp-root > mp-main-menu-top-nav > header "
                    "> div > bs-container-grid.menu-top-nav.vb-r-gap-none "
                    "> div > div.right-nav-side.authenticated "
                    "> mp-button-upload-assets > bs-square-button > button > span",
                )
            )
        )
        elem.click()

        # Click "My Uploads" in dropdown
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#mat-menu-panel-8 > div > button:nth-child(3) > span",
                )
            )
        )
        elem.click()

        # Click "+ Create media"
        elem = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (
                    By.CSS_SELECTOR,
                    "#app-body > mp-root > mp-upload-files-nav > nav "
                    "> div.btn-create > bs-square-button > button",
                )
            )
        )
        elem.click()

        # Click to start a new track upload
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#app-body > mp-root > div > div > ng-component "
                    "> mp-component-container > div > div > div "
                    "> section:nth-child(1) > button",
                )
            )
        )
        elem.click()

        # ============================================================
        # 4. FILL IN TRACK METADATA
        # ============================================================

        # --- Title ---
        title_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#app-body > mp-root > div > div > ng-component "
                    "> mp-track-form > div > form "
                    "> fieldset.general-information > mat-card "
                    "> div.track-form > section.track-info-section "
                    "> div.track-title > div > input",
                )
            )
        )
        title_input.clear()
        title_input.send_keys(beat_title)

        # --- Tags ---
        if tags:
            tag_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (
                        By.CSS_SELECTOR,
                        "#app-body > mp-root > div > div > ng-component "
                        "> mp-track-form > div > form "
                        "> fieldset.general-information > mat-card "
                        "> div.track-form > section.track-info-section "
                        "> div.track-tags > mp-tags-input "
                        "> div.input-text > div > input",
                    )
                )
            )
            for tag in tags[:3]:
                tag_input.send_keys(tag)
                tag_input.send_keys(Keys.RETURN)
                time.sleep(0.3)

        # --- BPM (optional) ---
        if bpm is not None:
            try:
                bpm_elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "#app-body > mp-root > div > div > ng-component "
                            "> mp-track-form > div > form "
                            "> fieldset.track-details > mat-card "
                            "> div.track-details-info > section:nth-child(2) "
                            "> div.track-bpm > div > input",
                        )
                    )
                )
                bpm_elem.clear()
                bpm_elem.send_keys(str(bpm))
            except Exception:
                print("[BeatStars] Warning: could not set BPM field")

        # --- Key (optional) ---
        # Конвертируем сырую тональность в BeatStars-формат (только Major/Minor)
        bs_key = convert_key_to_beatstars(key)
        if bs_key and bs_key in KEY_DICT:
            try:
                key_elem = WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.NAME, "keyNote"))
                )
                key_elem.click()
                key_select = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, f"//*[text()='{KEY_DICT[bs_key]}']")
                    )
                )
                key_select.click()
            except Exception:
                print("[BeatStars] Warning: could not set key field")

        # ============================================================
        # 5. UPLOAD MP3 (tagged track)
        # ============================================================
        elem = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#tagged-tracks > button")
            )
        )
        driver.execute_script("arguments[0].click();", elem)

        # Click cloud/device icon to open file picker
        elem = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#file-dialog > div > ul > li:nth-child(1) > div > i")
            )
        )
        elem.click()

        # Send file path to hidden input
        elem = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "#file-dialog > div > div > div > mp-step-my-device "
                    "> div > input[type=file]",
                )
            )
        )
        elem.send_keys(os.path.abspath(mp3_path))

        # ============================================================
        # 6. UPLOAD WAV (untagged track) — optional
        # ============================================================
        if wav_path and os.path.exists(wav_path):
            try:
                elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, "#un-tagged-tracks > button")
                    )
                )
                driver.execute_script("arguments[0].click();", elem)

                elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.CSS_SELECTOR,
                            "#file-dialog > div > ul > li:nth-child(1) > div > i",
                        )
                    )
                )
                elem.click()

                elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "#file-dialog > div > div > div > mp-step-my-device "
                            "> div > input[type=file]",
                        )
                    )
                )
                elem.send_keys(os.path.abspath(wav_path))
            except Exception:
                print("[BeatStars] Warning: could not upload WAV file")

        # ============================================================
        # 7. UPLOAD COVER IMAGE
        # ============================================================
        if cropped_cover and os.path.exists(cropped_cover):
            try:
                # Click "Upload New Image"
                elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//*[text()=' Upload New Image ']")
                    )
                )
                driver.execute_script("arguments[0].click();", elem)

                # Click "Upload file"
                elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "// *[text() = 'Upload file']")
                    )
                )
                driver.execute_script("arguments[0].click();", elem)

                # Click cloud icon (second option — "My Device" alternative)
                elem = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (
                            By.CSS_SELECTOR,
                            "#file-dialog > div > ul > li:nth-child(2) > div > i",
                        )
                    )
                )
                elem.click()

                # Send file path
                elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            "#uppy-drag-drop > div > button > input",
                        )
                    )
                )
                elem.send_keys(os.path.abspath(cropped_cover))

                # Click "Save Crop"
                elem = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "// *[text() = 'Save Crop']")
                    )
                )
                elem.click()
            except Exception:
                print("[BeatStars] Warning: could not upload cover image")

        # ============================================================
        # DONE — leave browser open for manual review
        # ============================================================
        return {
            "success": True,
            "error": None,
            "message": (
                "BeatStars upload form filled successfully. "
                "Browser left open for manual review and publish date selection."
            ),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"BeatStars upload failed: {e}",
            "message": None,
        }
