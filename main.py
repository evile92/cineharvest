"""Google Collection Extractor - Main CLI Entry Point.

Automates the extraction of movie and series titles from Google Collections
using Playwright Chromium with robust multi-strategy parsing, infinite scrolling,
and UTF-8 file exports (TXT, JSON, CSV, Letterboxd CSV, and Markdown).
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

from config import (
    DEFAULT_COLLECTION_URL,
    OUTPUT_TXT_PATH,
    OUTPUT_JSON_PATH,
    OUTPUT_CSV_PATH,
    OUTPUT_LETTERBOXD_PATH,
    OUTPUT_MD_PATH,
    DEFAULT_SESSION_PATH,
    DEBUG_DIR,
    DEBUG_LOG_PATH,
    HEADLESS,
    MAX_SCROLLS,
    SCROLL_DELAY,
    NO_CHANGE_LIMIT,
)
from cleaner import (
    clean_title,
    remove_duplicates_preserve_order,
    export_to_csv,
    export_to_letterboxd_csv,
    export_to_markdown,
)
from extractor import (
    launch_browser,
    open_collection,
    scroll_until_complete,
    extract_collection_data,
    save_debug_artifacts,
    save_session,
    setup_network_interception,
    ExtractionError,
)
from tmdb import enrich_items_with_tmdb

# Set Windows console to UTF-8 to prevent any UnicodeEncodeError in terminal prints
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def setup_logger(debug_mode: bool) -> logging.Logger:
    """Configure console and debug file logging."""
    logger = logging.getLogger("google_collection_extractor")
    logger.setLevel(logging.DEBUG if debug_mode else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    if debug_mode:
        fh = logging.FileHandler(DEBUG_LOG_PATH, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def save_txt(items: List[Dict[str, Any]], target_path: Path) -> None:
    """Save extracted titles to TXT file, one clean title per line in UTF-8."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        for item in items:
            title = item.get("title", "").strip()
            if title:
                f.write(f"{title}\n")


def save_json(items: List[Dict[str, Any]], target_path: Path) -> None:
    """Save items with metadata (title, url, type) to JSON file in UTF-8."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def print_summary(
    items_discovered: int,
    duplicates_count: int,
    unique_count: int,
    txt_path: Path,
    json_path: Path,
    csv_path: Path,
    letterboxd_path: Path,
    md_path: Path,
    strategy_used: str,
    debug_mode: bool,
) -> None:
    """Print the final clean summary matching the required terminal format."""
    print("========================================")
    print("Extraction Complete")
    print(f"Items discovered : {items_discovered}")
    print(f"Duplicates       : {duplicates_count}")
    print(f"Unique titles    : {unique_count}")
    print("Exported Files:")
    print(f"  [TXT]        : {txt_path}")
    print(f"  [JSON]       : {json_path}")
    print(f"  [CSV]        : {csv_path}")
    print(f"  [Letterboxd] : {letterboxd_path}")
    print(f"  [Markdown]   : {md_path}")
    if debug_mode:
        print(f"Strategy used    : {strategy_used}")
        print(f"Debug artifacts  : {DEBUG_DIR}")
    print("[✓] Done!")
    print("========================================")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract movie and series titles from Google Collections into clean TXT, JSON, CSV, Letterboxd, and Markdown."
    )
    parser.add_argument(
        "--url",
        type=str,
        default=DEFAULT_COLLECTION_URL,
        help="Google Collection shareable URL",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode (saves screenshots, page HTML, and verbose logs)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run Chromium with a visible graphical window (useful for manual login/solving CAPTCHA)",
    )
    parser.add_argument(
        "--save-session",
        action="store_true",
        help="Save browser authentication session/cookies to auth/session.json for reuse",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="Path to an existing session JSON file (defaults to auth/session.json if exists)",
    )
    parser.add_argument(
        "--tmdb-key",
        type=str,
        default=None,
        help="Optional TMDB API key to enrich extracted titles with release year, ratings, and posters",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=MAX_SCROLLS,
        help=f"Maximum scroll iterations (default: {MAX_SCROLLS})",
    )
    parser.add_argument(
        "--scroll-delay",
        type=float,
        default=SCROLL_DELAY,
        help=f"Delay between scroll iterations in seconds (default: {SCROLL_DELAY})",
    )
    parser.add_argument(
        "--output-txt",
        type=str,
        default=str(OUTPUT_TXT_PATH),
        help=f"Path for output TXT file (default: {OUTPUT_TXT_PATH})",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=str(OUTPUT_JSON_PATH),
        help=f"Path for output JSON file (default: {OUTPUT_JSON_PATH})",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=str(OUTPUT_CSV_PATH),
        help=f"Path for output CSV file (default: {OUTPUT_CSV_PATH})",
    )
    parser.add_argument(
        "--output-letterboxd",
        type=str,
        default=str(OUTPUT_LETTERBOXD_PATH),
        help=f"Path for output Letterboxd CSV import file (default: {OUTPUT_LETTERBOXD_PATH})",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default=str(OUTPUT_MD_PATH),
        help=f"Path for output Markdown checklist file (default: {OUTPUT_MD_PATH})",
    )

    args = parser.parse_args()

    txt_file = Path(args.output_txt).resolve()
    json_file = Path(args.output_json).resolve()
    csv_file = Path(args.output_csv).resolve()
    letterboxd_file = Path(args.output_letterboxd).resolve()
    md_file = Path(args.output_md).resolve()
    headless_mode = False if args.no_headless else HEADLESS

    # Session file selection
    session_file = None
    if args.session:
        session_file = args.session
    elif DEFAULT_SESSION_PATH.exists():
        session_file = str(DEFAULT_SESSION_PATH)

    logger = setup_logger(args.debug)
    log_messages: List[str] = []

    def log_and_record(msg: str):
        log_messages.append(f"[{time.strftime('%X')}] {msg}")
        if args.debug:
            logger.debug(msg)

    print("========================================")
    print("Google Collection Extractor")
    print("[+] Starting browser...")
    log_and_record("Launching browser")

    pw = browser = context = page = None
    try:
        pw, browser, context, page = launch_browser(
            headless=headless_mode,
            session_path=session_file,
        )

        # Setup wire-level network interception to harvest items streaming from Google
        intercepted_network_items: List[Dict[str, Any]] = []
        setup_network_interception(page, intercepted_network_items)

        print("[+] Opening collection...")
        log_and_record(f"Opening URL: {args.url}")
        open_collection(page, args.url)

        print("[+] Loading JavaScript...")
        log_and_record("Waiting for dynamic content to hydrate")
        time.sleep(2)

        print("[+] Scanning collection...")
        print("[+] Scrolling...")
        log_and_record("Starting infinite scroll")

        discovered_counts = []

        def on_item_discovered(count: int):
            discovered_counts.append(count)
            print(f"[+] Items discovered: {count}")
            log_and_record(f"Items discovered: {count}")

        scroll_until_complete(
            page,
            progress_callback=on_item_discovered,
            scroll_delay=args.scroll_delay,
            max_scrolls=args.max_scrolls,
            no_change_limit=NO_CHANGE_LIMIT,
        )

        print("[+] Extracting titles...")
        print("[+] Cleaning data...")
        print("[+] Removing duplicates...")
        log_and_record("Executing multi-strategy data extraction")

        unique_items, strategy_used = extract_collection_data(
            page,
            intercepted_items=intercepted_network_items,
        )
        log_and_record(f"Strategy used: {strategy_used}, total items: {len(unique_items)}")

        # Optional TMDB Enrichment
        if args.tmdb_key:
            print("[+] Enriching metadata via TMDB API...")
            log_and_record("Enriching items with TMDB metadata")
            unique_items = enrich_items_with_tmdb(unique_items, args.tmdb_key)

        # Metrics calculation
        total_discovered = discovered_counts[-1] if discovered_counts else len(unique_items)
        unique_count = len(unique_items)
        duplicates_count = max(0, total_discovered - unique_count)

        print("[+] Saving results (TXT, JSON, CSV, Letterboxd, Markdown)...")
        log_and_record("Writing export files")
        save_txt(unique_items, txt_file)
        save_json(unique_items, json_file)
        export_to_csv(unique_items, csv_file)
        export_to_letterboxd_csv(unique_items, letterboxd_file)
        export_to_markdown(unique_items, md_file)

        # Save session if requested
        if args.save_session and context:
            save_session(context, DEFAULT_SESSION_PATH)
            print(f"[+] Session saved to {DEFAULT_SESSION_PATH}")

        # In debug mode, save screenshot and full page HTML
        if args.debug:
            save_debug_artifacts(page, log_messages)

        print_summary(
            items_discovered=total_discovered,
            duplicates_count=duplicates_count,
            unique_count=unique_count,
            txt_path=txt_file,
            json_path=json_file,
            csv_path=csv_file,
            letterboxd_path=letterboxd_file,
            md_path=md_file,
            strategy_used=strategy_used,
            debug_mode=args.debug,
        )
        return 0

    except ExtractionError as e:
        print(f"\n[-] Error: {e}", file=sys.stderr)
        log_and_record(f"ExtractionError: {e}")
        if page:
            save_debug_artifacts(page, log_messages)
        return 1

    except Exception as e:
        print(f"\n[-] An unexpected error occurred: {e}", file=sys.stderr)
        log_and_record(f"Unexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        if page:
            save_debug_artifacts(page, log_messages)
        return 1

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
