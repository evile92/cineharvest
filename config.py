"""Configuration settings and constants for Google Collection Extractor.

All system defaults, timeouts, selectors, and output paths are centralized
here.
"""

from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output"
DEBUG_DIR = PROJECT_ROOT / "debug"

# Ensure runtime directories exist
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Default URLs
DEFAULT_COLLECTION_URL = (
    "https://www.google.com/collections/s/list/eCcG-ojrWElfrGZN89sypy8zJMwd0Q/pjO2sgVGeCI"
)

# Output file paths
OUTPUT_TXT_PATH = OUTPUT_DIR / "movies_and_series.txt"
OUTPUT_JSON_PATH = OUTPUT_DIR / "movies_and_series.json"

# Debug output file paths
DEBUG_SCREENSHOT_PATH = DEBUG_DIR / "screenshot.png"
DEBUG_HTML_PATH = DEBUG_DIR / "page.html"
DEBUG_LOG_PATH = DEBUG_DIR / "extraction.log"

# Playwright & Browser Settings
HEADLESS = True
BROWSER_TIMEOUT_MS = 30000
PAGE_TIMEOUT = 30000

# Infinite Scroll Configuration
MAX_SCROLLS = 120
SCROLL_DELAY = 1.5  # Seconds between scrolls
NO_CHANGE_LIMIT = 5  # Stop after N consecutive scrolls with 0 new items
SCROLL_STEP_PX = 1200  # Smooth incremental scroll distance

# Browser Anti-Detection & Headers
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

VIEWPORT = {"width": 1440, "height": 900}
LOCALE = "en-US"

# Debug Mode Flag
DEBUG = False
