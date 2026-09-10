# Google Collection Media Extractor

A robust, production-grade Python tool designed to automate the extraction of movie and TV series titles from public **Google Collections** (such as Google Search Watchlists). Powered by **Playwright**, it handles dynamic JavaScript rendering, automated infinite scrolling, data sanitization, and exports clean titles into structured TXT and JSON formats.

---

## Features

- **Smart Infinite Scroll:** Dynamically tracks item count plateaus and handles lazy loading without relying on fixed, arbitrary timeouts or falling into infinite loops.
- **Multi-Strategy Extraction Engine:** Employs a tiered extraction hierarchy (DOM title spans `jsname="r4nke"`, search anchor attributes, card containers, and embedded page state) ensuring resilience against UI layout changes.
- **Accurate Data Sanitization:** Strips away Google UI buttons (*Save to collection*, *More options*, *Share*, *Remove*) and HTML entities (`&amp;`, `&#39;`) while preserving authentic numbers in titles (e.g., *12 Monkeys*, *28 Days Later*, *1923*).
- **Order-Preserving Deduplication:** Eliminates duplicate entries while strictly preserving the original chronological appearance in the collection.
- **Universal UTF-8 Encoding:** Flawless support for international characters, Arabic, accents, and diverse Unicode sets.
- **Browser Fallback Mechanism:** Automatically utilizes Playwright's Chromium, with automatic fallback to locally installed Google Chrome or Microsoft Edge.
- **Comprehensive Debug Mode (`--debug`):** Captures full-page screenshots (`debug/screenshot.png`), complete DOM HTML snapshots (`debug/page.html`), and detailed timestamps in `debug/extraction.log`.
- **Graceful Error Handling:** Provides user-friendly CLI feedback for network drops, private collections requiring authentication, and CAPTCHA alerts.

---

## Prerequisites

- **Python:** 3.10 or newer
- **Operating System:** Windows, macOS, or Linux

---

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/evile92/google-collection-extractor.git
   cd google-collection-extractor
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Install the Playwright Chromium browser:**
   ```bash
   playwright install chromium
   ```

---

## Usage

### 1. Default Run (Preconfigured Collection)
Run the script directly to extract from the default collection URL:
```bash
python main.py
```

### 2. Extract Any Custom Google Collection
Pass any shareable Google Collection URL via the `--url` argument:
```bash
python main.py --url "https://www.google.com/collections/s/list/YOUR_LIST_ID/..."
```

### 3. Diagnostic & Debug Mode
Run with `--debug` to generate a full-page screenshot, HTML source dump, and detailed execution log:
```bash
python main.py --debug
```

### 4. Interactive Browser Window (Solve CAPTCHA or Sign In)
If the collection is private or requires manual Google sign-in:
```bash
python main.py --no-headless
```
This launches a visible browser window where you can log in manually; the script will resume extraction once complete.

### 5. Fine-Tuning Scrolling Parameters
```bash
python main.py --max-scrolls 150 --scroll-delay 2.0
```

---

## Project Structure

```
google-collection-extractor/
│
├── main.py              # CLI entry point, argument parsing, and workflow execution
├── extractor.py         # Playwright automation, infinite scroll, and multi-strategy extraction
├── cleaner.py           # Data cleansing, HTML unescaping, and order-preserving deduplication
├── config.py            # Global constants, default timeouts, and path definitions
├── requirements.txt     # Python package requirements (playwright)
├── README.md            # Documentation and usage guide
│
├── output/              # Extracted datasets
│   ├── movies_and_series.txt    # Clean, one-per-line plain text list
│   └── movies_and_series.json   # Structured JSON with title, URL, and media type
│
└── debug/               # Generated only during errors or when --debug is active
    ├── screenshot.png
    ├── page.html
    └── extraction.log
```

---

## Output Formats

### Plain Text (`output/movies_and_series.txt`)
Each unique title is written to an independent line in UTF-8:
```text
The Mentalist
Fallout
Marrowbone
Jeepers Creepers
The Constant Gardener
Lawless
World War II with Tom Hanks
Widow's Bay
The Secret Life of Walter Mitty
From Beijing with Love
12 Monkeys
28 Days Later
1923
```

### JSON Format (`output/movies_and_series.json`)
Structured metadata representation:
```json
[
  {
    "title": "The Mentalist",
    "url": "https://www.google.com/search?q=The+Mentalist...",
    "type": null
  },
  {
    "title": "Fallout",
    "url": "https://www.google.com/search?q=Fallout...",
    "type": null
  }
]
```
*(Note: `type` defaults to `null` whenever reliable categorization cannot be verified from the collection card)*.

---

## Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| `Chromium browser is not installed` | Missing browser binaries | Run `playwright install chromium` |
| `Google is requesting account sign-in` | The collection is set to private | Run `python main.py --no-headless` and log in via the browser window |
| `Google returned HTTP status 404` | Invalid or expired link | Ensure the collection link is public and accessible |
| `UnicodeEncodeError` in legacy terminals | Terminal output encoding is not UTF-8 | The script auto-configures UTF-8; you can also run `chcp 65001` on Windows |

---

## License

This project is licensed under the MIT License.
