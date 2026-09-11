# Google Collection Media Extractor

A robust, production-grade Python tool designed to automate the extraction of movie and TV series titles from public and private **Google Collections** (such as Google Search Watchlists). Powered by **Playwright**, it handles dynamic JavaScript rendering, automated infinite scrolling, wire-level network interception, data sanitization, and exports clean titles into **TXT, JSON, CSV, Letterboxd-ready CSV, and Markdown** formats.

---

## Features

- **Smart Infinite Scroll & Network Interception:** Dynamically monitors item count plateaus and intercepts HTTP stream packets directly from Google's backend, ensuring lightning-fast data capture without missing items.
- **Multi-Strategy Extraction Engine:** Employs a tiered extraction hierarchy (DOM title spans `jsname="r4nke"`, search anchor attributes, card containers, and embedded page state) ensuring resilience against UI layout changes.
- **Letterboxd & IMDb Ready Export:** Generates an official `letterboxd_watchlist.csv` with standard `Title, Year, URL` headers for instant 1-click import into [Letterboxd](https://letterboxd.com/import/).
- **Markdown Checklist & Table:** Exports a formatted Markdown document (`movies_and_series.md`) with interactive task checkboxes and detailed summary tables, ready for **Notion**, **Obsidian**, or GitHub.
- **Session & Cookie Persistence:** Save authenticated browser sessions via `--save-session` to scrape private watchlists repeatedly without needing to log in every time.
- **Optional TMDB API Enrichment:** Pass `--tmdb-key` to automatically query The Movie Database (TMDB) and enrich your collection with release years, vote ratings, and high-res poster URLs.
- **Accurate Data Sanitization:** Strips away Google UI buttons (*Save to collection*, *More options*, *Share*, *Remove*) and HTML entities (`&amp;`, `&#39;`) while preserving authentic numbers in titles (e.g., *12 Monkeys*, *28 Days Later*, *1923*).
- **Order-Preserving Deduplication:** Eliminates duplicate entries while strictly preserving the original chronological appearance in the collection.
- **Universal UTF-8 Encoding:** Flawless support for international characters, Arabic, accents, and diverse Unicode sets.
- **Browser Fallback Mechanism:** Automatically utilizes Playwright's Chromium, with fallback to locally installed Google Chrome or Microsoft Edge.
- **Comprehensive Debug Mode (`--debug`):** Captures full-page screenshots (`debug/screenshot.png`), complete DOM HTML snapshots (`debug/page.html`), and execution timestamps in `debug/extraction.log`.

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

## How to Make Your Google Collection Public

To extract items from your own Google Collection or Watchlist without needing to log in, generate a public share link:

1. Open your collection on [Google Collections / Saved](https://www.google.com/interests/saved).
2. Click the **Share** button in the top-right corner.
3. Under **"Who can access"**, switch from *"Only you"* to **"Anyone with link"** (*Anyone with the link can view*).
4. Click **"Share link"** to copy the URL.
5. Pass this URL to the tool:
   ```bash
   python main.py --url "https://www.google.com/collections/s/list/..."
   ```

*(Note: If you prefer keeping your collection private, see [Handling Private Collections](#handling-private-collections-session-persistence) below).*

---

## Usage Guide

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

### 3. Handling Private Collections (Session Persistence)
For private collections that require your Google account:
1. Run once with a visible browser window and `--save-session`:
   ```bash
   python main.py --no-headless --save-session --url "YOUR_PRIVATE_COLLECTION_URL"
   ```
2. Log into your Google account inside the browser window.
3. The session is saved to `auth/session.json`. For subsequent runs, the tool automatically uses this saved session headlessly!

### 4. Optional TMDB Metadata Enrichment
Fetch release years, ratings, and poster image URLs from TMDB:
```bash
python main.py --tmdb-key "YOUR_TMDB_API_KEY"
```

### 5. Diagnostic & Debug Mode
Run with `--debug` to generate a full-page screenshot, HTML source dump, and detailed execution log:
```bash
python main.py --debug
```

### 6. Fine-Tuning Scrolling Parameters
```bash
python main.py --max-scrolls 150 --scroll-delay 2.0
```

---

## Output Formats

Upon completion, all datasets are exported cleanly into the `output/` directory:

| Format | File Path | Description |
|---|---|---|
| **TXT** | `output/movies_and_series.txt` | Clean plain text with one title per line |
| **JSON** | `output/movies_and_series.json` | Structured JSON with titles, search URLs, and media types |
| **CSV** | `output/movies_and_series.csv` | Full tabular dataset with titles, types, years, and ratings |
| **Letterboxd** | `output/letterboxd_watchlist.csv` | Official format ready for [Letterboxd Import](https://letterboxd.com/import/) |
| **Markdown** | `output/movies_and_series.md` | Interactive checklist and GFM table for Notion / Obsidian |

### How to Import into Letterboxd
1. Go to [Letterboxd Import](https://letterboxd.com/import/).
2. Select or drag & drop `output/letterboxd_watchlist.csv`.
3. Choose **"Add to Watchlist"** and confirm. All titles will be imported directly!

---

## Project Structure

```
google-collection-extractor/
│
├── main.py              # CLI entry point, argument parsing, and workflow execution
├── extractor.py         # Playwright automation, network interception, and multi-strategy extraction
├── cleaner.py           # Cleansing, HTML unescaping, CSV, and Markdown exporters
├── tmdb.py              # Optional TMDB metadata enrichment module
├── config.py            # Global constants, default timeouts, and path definitions
├── requirements.txt     # Python package requirements
├── README.md            # Documentation and usage guide
│
├── output/              # Extracted datasets
│   ├── movies_and_series.txt        # Plain text list
│   ├── movies_and_series.json       # Structured JSON
│   ├── movies_and_series.csv        # Comprehensive CSV
│   ├── letterboxd_watchlist.csv     # Letterboxd import CSV
│   └── movies_and_series.md         # Markdown checklist & table
│
├── auth/                # Saved browser session state (git-ignored)
│   └── session.json
│
└── debug/               # Generated only during errors or when --debug is active
    ├── screenshot.png
    ├── page.html
    └── extraction.log
```

---

## Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| `Chromium browser is not installed` | Missing browser binaries | Run `playwright install chromium` |
| `Google is requesting account sign-in` | Collection is private | Run `python main.py --no-headless --save-session` to log in once |
| `Google returned HTTP status 404 / 302` | Expired or invalid share link | Open Google Collections, click **Share**, choose **Anyone with link**, and copy a fresh link |
| `UnicodeEncodeError` in legacy terminals | Terminal output encoding is not UTF-8 | The script auto-configures UTF-8; you can also run `chcp 65001` on Windows |

---

## License

This project is licensed under the MIT License.
