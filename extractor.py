"""Core extraction engine for Google Collection.

Utilizes Playwright to automate Chromium, handles dynamic content loading,
smart infinite scrolling, and multi-stage extraction strategies.
"""

import asyncio
import logging
import os
import sys
import time
from typing import Callable, Dict, Any, List, Optional, Tuple

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

from config import (
    HEADLESS,
    BROWSER_TIMEOUT_MS,
    PAGE_TIMEOUT,
    MAX_SCROLLS,
    SCROLL_DELAY,
    NO_CHANGE_LIMIT,
    USER_AGENT,
    VIEWPORT,
    LOCALE,
    DEBUG_SCREENSHOT_PATH,
    DEBUG_HTML_PATH,
    DEBUG_LOG_PATH,
)
from cleaner import clean_title, is_valid_title, remove_duplicates_preserve_order, detect_media_type

# Configure logger
logger = logging.getLogger("google_collection_extractor")


class ExtractionError(Exception):
    """Custom user-friendly exception for extraction issues."""
    pass


def launch_browser(
    headless: bool = True,
    session_path: Optional[str] = None,
) -> Tuple[Playwright, Browser, BrowserContext, Page]:
    """Launch Playwright Chromium instance with anti-detection options and optional session restoration."""
    pw = sync_playwright().start()
    browser_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-infobars",
        "--disable-dev-shm-usage",
        "--lang=en-US,en",
    ]

    browser = None
    launch_errors = []

    # 1. Try bundled Playwright Chromium
    try:
        browser = pw.chromium.launch(headless=headless, args=browser_args)
    except Exception as e:
        launch_errors.append(f"Bundled Chromium: {e}")

    # 2. Fallback to installed Google Chrome
    if not browser:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=headless, args=browser_args)
        except Exception as e:
            launch_errors.append(f"System Chrome: {e}")

    # 3. Fallback to installed Microsoft Edge
    if not browser:
        try:
            browser = pw.chromium.launch(channel="msedge", headless=headless, args=browser_args)
        except Exception as e:
            launch_errors.append(f"System Edge: {e}")

    if not browser:
        pw.stop()
        raise ExtractionError(
            "Could not launch any Chromium-compatible browser.\n"
            f"Details: {'; '.join(launch_errors)}\n"
            "Please run: playwright install chromium"
        )

    context_kwargs: Dict[str, Any] = {
        "user_agent": USER_AGENT,
        "viewport": VIEWPORT,
        "locale": LOCALE,
        "ignore_https_errors": True,
    }

    if session_path and os.path.exists(session_path):
        context_kwargs["storage_state"] = session_path
        logger.info("Loaded browser session from %s", session_path)

    context = browser.new_context(**context_kwargs)
    page = context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT)
    return pw, browser, context, page


def save_session(context: BrowserContext, target_path: Any) -> None:
    """Save browser authentication state and cookies to a JSON file."""
    from pathlib import Path
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(target))
    logger.info("Browser session saved to %s", target)


def setup_network_interception(page: Page, intercepted_collector: List[Dict[str, Any]]) -> None:
    """Listen to HTTP responses to harvest collection item data directly from the wire."""
    import re
    import urllib.parse

    def handle_response(response):
        try:
            url = response.url
            if "SaveUi" in url or "batchexecute" in url:
                text = response.text()
                # Find occurrences of google search urls with titles
                matches = re.findall(r'"https://www\.google\.com/search\?q=([^"&]+)[^"]*"', text)
                for q in matches:
                    title = urllib.parse.unquote_plus(q)
                    intercepted_collector.append({
                        "title": title,
                        "url": f"https://www.google.com/search?q={q}",
                        "meta": None,
                    })
        except Exception:
            pass

    page.on("response", handle_response)


def open_collection(page: Page, url: str) -> None:
    """Navigate to the Google Collection URL and check for access barriers."""
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT)
        if response and response.status >= 400:
            raise ExtractionError(
                f"Google returned HTTP status {response.status} for this collection.\n"
                f"Please verify that the URL is public and accessible."
            )
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(
            f"Failed to connect to Google Collection URL.\n"
            f"Error details: {e}\n"
            f"Please check your internet connection and verify the URL."
        ) from e

    # Wait for initial hydration
    time.sleep(2)

    # Check for CAPTCHA or Login requirements or Expired Share Links
    current_url = page.url
    if "save?error=1" in current_url or "interests/saved?error=1" in current_url:
        raise ExtractionError(
            "Google returned an error for this collection link (redirected to /save?error=1).\n"
            "The share link may have expired, or its sharing permissions were updated in Google Collections.\n"
            "Solution: In your Google Collection, click 'Share' -> choose 'Anyone with link' -> copy a fresh link."
        )

    if "accounts.google.com" in current_url:
        raise ExtractionError(
            "Google is requesting account sign-in to view this collection.\n"
            "If this is a private collection, run: python main.py --no-headless --save-session\n"
            "to log in once in the browser window, then the extractor will continue automatically."
        )
    if "sorry/index" in current_url:
        raise ExtractionError(
            "Google triggered an unusual traffic challenge (CAPTCHA).\n"
            "Please wait a few minutes or run with --no-headless to solve it in the browser."
        )


def _get_current_item_count(page: Page) -> int:
    """Fast check of current number of item containers loaded in the DOM."""
    try:
        # Check standard item selectors in Google Collection
        count = page.evaluate("""() => {
            const spans = document.querySelectorAll('span[jsname="r4nke"]');
            if (spans.length > 0) return spans.length;
            const links = document.querySelectorAll('a[href*="/search?q="]');
            if (links.length > 0) return links.length;
            const cards = document.querySelectorAll('div[jsname="Qm9wMc"], div.C4h8Ec');
            return cards.length;
        }""")
        return int(count)
    except Exception:
        return 0


def scroll_until_complete(
    page: Page,
    progress_callback: Optional[Callable[[int], None]] = None,
    scroll_delay: float = SCROLL_DELAY,
    max_scrolls: int = MAX_SCROLLS,
    no_change_limit: int = NO_CHANGE_LIMIT,
) -> int:
    """Intelligently scrolls the collection until no new items are loaded.
    
    Monitors DOM changes, waits for lazy-loaded assets, and halts when items plateau.
    """
    last_count = _get_current_item_count(page)
    no_change_attempts = 0
    scroll_count = 0

    if progress_callback and last_count > 0:
        progress_callback(last_count)

    while scroll_count < max_scrolls:
        scroll_count += 1

        # Scroll to bottom smoothly
        page.evaluate("""() => {
            window.scrollTo({
                top: document.body.scrollHeight,
                behavior: 'smooth'
            });
        }""")

        # Wait for dynamic network requests and rendering
        time.sleep(scroll_delay)

        new_count = _get_current_item_count(page)

        if new_count > last_count:
            last_count = new_count
            no_change_attempts = 0
            if progress_callback:
                progress_callback(new_count)
        else:
            no_change_attempts += 1
            # Secondary check: slight scroll up and back down to trigger lazy observers
            if no_change_attempts >= 2:
                page.evaluate("window.scrollBy(0, -300)")
                time.sleep(0.5)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(scroll_delay)
                new_count = _get_current_item_count(page)
                if new_count > last_count:
                    last_count = new_count
                    no_change_attempts = 0
                    if progress_callback:
                        progress_callback(new_count)
                    continue

            if no_change_attempts >= no_change_limit:
                logger.info("Reached end of collection: no new items loaded after %d attempts.", no_change_attempts)
                break

    return last_count


def _strategy_1_dom_spans(page: Page) -> List[Dict[str, Any]]:
    """Strategy 1: Primary Google Collections title spans (jsname='r4nke')."""
    raw_data = page.evaluate("""() => {
        const results = [];
        const spans = document.querySelectorAll('span[jsname="r4nke"]');
        for (const span of spans) {
            const title = span.innerText || span.textContent;
            // Find enclosing anchor or nearby anchor
            const anchor = span.closest('a') || span.closest('.C4h8Ec')?.querySelector('a');
            const url = anchor ? anchor.href : null;
            // Check for subtitle / type label in sibling or parent elements
            const card = span.closest('.C4h8Ec') || span.closest('div[jsname="Qm9wMc"]');
            const metaText = card ? card.innerText : null;
            results.push({
                title: title,
                url: url,
                meta: metaText
            });
        }
        return results;
    }""")
    return raw_data


def _strategy_2_search_links(page: Page) -> List[Dict[str, Any]]:
    """Strategy 2: Links pointing to Google Search with aria-labels."""
    raw_data = page.evaluate("""() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/search?q="]');
        for (const link of links) {
            const label = link.getAttribute('aria-label') || link.innerText;
            const url = link.href;
            results.push({
                title: label,
                url: url,
                meta: null
            });
        }
        return results;
    }""")
    return raw_data


def _strategy_3_card_containers(page: Page) -> List[Dict[str, Any]]:
    """Strategy 3: Card containers (.C4h8Ec, div[jsname='Qm9wMc'])."""
    raw_data = page.evaluate("""() => {
        const results = [];
        const cards = document.querySelectorAll('div[jsname="Qm9wMc"], div.C4h8Ec');
        for (const card of cards) {
            const anchor = card.querySelector('a');
            const titleEl = card.querySelector('.VeoBtc, h3, [role="heading"]') || anchor;
            const title = titleEl ? (titleEl.innerText || titleEl.textContent) : null;
            const url = anchor ? anchor.href : null;
            results.push({
                title: title,
                url: url,
                meta: card.innerText
            });
        }
        return results;
    }""")
    return raw_data


def _strategy_4_script_state(page: Page) -> List[Dict[str, Any]]:
    """Strategy 4: Extract items embedded in page AF_initDataCallback / WIZ state."""
    raw_data = page.evaluate("""() => {
        const results = [];
        const scripts = document.querySelectorAll('script');
        for (const s of scripts) {
            const text = s.textContent || '';
            if (text.includes('AF_initDataCallback')) {
                // Search for titles associated with google.com/search?q=
                const regex = /"https:\\/\\/www\\.google\\.com\\/search\\?q=([^"&]+)[^"]*"/g;
                let match;
                while ((match = regex.exec(text)) !== null) {
                    const rawTitle = decodeURIComponent(match[1].replace(/\\+/g, ' '));
                    results.push({
                        title: rawTitle,
                        url: match[0].replace(/"/g, ''),
                        meta: null
                    });
                }
            }
        }
        return results;
    }""")
    return raw_data


def extract_collection_data(
    page: Page,
    intercepted_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Execute multi-strategy title extraction with fallback hierarchy.
    
    Returns the cleaned, deduplicated items and the name of the successful strategy.
    """
    strategies = [
        ("DOM Title Spans (jsname='r4nke')", _strategy_1_dom_spans),
        ("Search Link Attributes (aria-label)", _strategy_2_search_links),
        ("Card Containers (.C4h8Ec / Qm9wMc)", _strategy_3_card_containers),
        ("Inline Script State (AF_initDataCallback)", _strategy_4_script_state),
    ]

    if intercepted_items:
        strategies.append(("Network Interception Stream", lambda p: intercepted_items))

    for strat_name, strat_func in strategies:
        try:
            raw_items = strat_func(page)
            if not raw_items:
                continue

            # Clean and filter titles
            processed = []
            for item in raw_items:
                cleaned = clean_title(item.get("title"))
                if is_valid_title(cleaned):
                    media_type = detect_media_type(item.get("meta"))
                    processed.append({
                        "title": cleaned,
                        "url": item.get("url"),
                        "type": media_type,
                    })

            if processed:
                unique = remove_duplicates_preserve_order(processed)
                logger.info("Extraction succeeded using strategy '%s': %d unique titles found.", strat_name, len(unique))
                return unique, strat_name

        except Exception as e:
            logger.warning("Strategy '%s' encountered an error: %s", strat_name, e)
            continue

    raise ExtractionError(
        "Could not extract any titles from this collection.\n"
        "The collection might be empty, or Google changed the layout structure."
    )


def get_pagination_info(page: Page) -> Dict[str, Any]:
    """Inspect current pagination state and check if a Next page button exists.
    
    Detects Google Collections pagination footers such as '< 1-200 of 234 >'
    and assesses whether more items remain on subsequent pages.
    """
    try:
        info = page.evaluate("""() => {
            // Strategy 1: Find text matching '1-200 of 234' or '1-200 من 234'
            const regex = /\\b(\\d+)[\\s–-]+(\\d+)\\s+(?:of|من|de|sur|\\/)\\s+(\\d+)\\b/i;
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                const match = regex.exec(text);
                if (match) {
                    const start = parseInt(match[1], 10);
                    const end = parseInt(match[2], 10);
                    const total = parseInt(match[3], 10);
                    
                    const container = node.parentElement ? (node.parentElement.closest('div, nav, footer') || node.parentElement) : null;
                    if (container) {
                        const buttons = Array.from(container.querySelectorAll('button, div[role="button"], span[role="button"], a'));
                        let nextBtn = buttons.find(b => {
                            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                            return aria.includes('next') || aria.includes('تالي') || aria.includes('chevron_right');
                        });
                        if (!nextBtn && buttons.length >= 2) {
                            const afterButtons = buttons.filter(b => (node.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
                            nextBtn = afterButtons.length > 0 ? afterButtons[0] : buttons[buttons.length - 1];
                        }
                        
                        const isNextDisabled = nextBtn ? (
                            nextBtn.disabled === true ||
                            nextBtn.getAttribute('aria-disabled') === 'true' ||
                            nextBtn.classList.contains('disabled') ||
                            nextBtn.hasAttribute('disabled')
                        ) : (end >= total);
                        
                        return {
                            has_pagination: true,
                            current_text: match[0],
                            start: start,
                            end: end,
                            total: total,
                            has_next: !isNextDisabled && end < total,
                            is_last_page: isNextDisabled || end >= total
                        };
                    }
                }
            }
            
            // Strategy 2: Check for explicit Next button via aria-label
            const ariaBtn = document.querySelector('button[aria-label*="Next" i], button[aria-label*="تالي" i], [role="button"][aria-label*="Next" i]');
            if (ariaBtn) {
                const isDis = ariaBtn.disabled === true || ariaBtn.getAttribute('aria-disabled') === 'true';
                return {
                    has_pagination: true,
                    current_text: '',
                    has_next: !isDis,
                    is_last_page: isDis
                };
            }
            
            return {
                has_pagination: false,
                current_text: '',
                has_next: false,
                is_last_page: true
            };
        }""")
        return info or {"has_pagination": False, "has_next": False}
    except Exception as e:
        logger.warning("Failed to evaluate pagination info: %s", e)
        return {"has_pagination": False, "has_next": False}


def click_next_page(page: Page, previous_text: str = "") -> bool:
    """Click the next page button and wait for the new batch of collection cards to render."""
    try:
        clicked = page.evaluate("""() => {
            const regex = /\\b(\\d+)[\\s–-]+(\\d+)\\s+(?:of|من|de|sur|\\/)\\s+(\\d+)\\b/i;
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const text = node.textContent.trim();
                const match = regex.exec(text);
                if (match) {
                    const container = node.parentElement ? (node.parentElement.closest('div, nav, footer') || node.parentElement) : null;
                    if (container) {
                        const buttons = Array.from(container.querySelectorAll('button, div[role="button"], span[role="button"], a'));
                        let nextBtn = buttons.find(b => {
                            const aria = (b.getAttribute('aria-label') || '').toLowerCase();
                            return aria.includes('next') || aria.includes('تالي') || aria.includes('chevron_right');
                        });
                        if (!nextBtn && buttons.length >= 2) {
                            const afterButtons = buttons.filter(b => (node.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
                            nextBtn = afterButtons.length > 0 ? afterButtons[0] : buttons[buttons.length - 1];
                        }
                        if (nextBtn) {
                            const isDis = nextBtn.disabled === true || nextBtn.getAttribute('aria-disabled') === 'true';
                            if (!isDis) {
                                nextBtn.click();
                                return true;
                            }
                        }
                    }
                }
            }
            
            // Fallback: aria-label next
            const ariaBtn = document.querySelector('button[aria-label*="Next" i], button[aria-label*="تالي" i], [role="button"][aria-label*="Next" i]');
            if (ariaBtn) {
                const isDis = ariaBtn.disabled === true || ariaBtn.getAttribute('aria-disabled') === 'true';
                if (!isDis) {
                    ariaBtn.click();
                    return true;
                }
            }
            return false;
        }""")
        
        if not clicked:
            return False
            
        logger.info("Clicked Next Page button. Waiting for page transition...")
        time.sleep(1.5)
        # Scroll back to top to let lazy observers catch the new cards
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1.5)
        
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
            
        return True
    except Exception as e:
        logger.warning("Error clicking next page button: %s", e)
        return False


def extract_all_collection_pages(
    page: Page,
    intercepted_items: Optional[List[Dict[str, Any]]] = None,
    page_callback: Optional[Callable[[int, int], None]] = None,
    scroll_callback: Optional[Callable[[int], None]] = None,
    scroll_delay: float = SCROLL_DELAY,
    max_scrolls: int = MAX_SCROLLS,
    no_change_limit: int = NO_CHANGE_LIMIT,
    max_pages: int = 30,
) -> Tuple[List[Dict[str, Any]], str, int]:
    """Orchestrates infinite-scroll extraction across all pagination pages.
    
    Handles single-page collections and multi-page collections (e.g. 1-200 of 234),
    accumulates items from each page, advances pages via Next button, and deduplicates.
    
    Returns:
        (unique_items, strategy_used, total_pages_processed)
    """
    all_raw_items: List[Dict[str, Any]] = []
    strategies_used: List[str] = []
    current_page = 1

    while current_page <= max_pages:
        if page_callback:
            page_callback(current_page, len(all_raw_items))

        # 1. Scroll the current page until fully loaded
        scroll_until_complete(
            page,
            progress_callback=scroll_callback,
            scroll_delay=scroll_delay,
            max_scrolls=max_scrolls,
            no_change_limit=no_change_limit,
        )

        # 2. Extract items from current page
        page_items, strat = extract_collection_data(page, intercepted_items=intercepted_items)
        if strat not in strategies_used:
            strategies_used.append(strat)
        all_raw_items.extend(page_items)
        logger.info("Page %d complete: collected %d items from this page (running total: %d).",
                    current_page, len(page_items), len(all_raw_items))

        # 3. Check pagination info
        pag_info = get_pagination_info(page)
        logger.info("Pagination state on page %d: %s", current_page, pag_info)

        if not pag_info.get("has_next"):
            logger.info("Reached the final page of the collection (%d pages processed).", current_page)
            break

        # 4. Click Next Page and transition
        prev_text = pag_info.get("current_text", "")
        success = click_next_page(page, previous_text=prev_text)
        if not success:
            logger.info("No further pages accessible or next button reached limit.")
            break

        current_page += 1

    unique_items = remove_duplicates_preserve_order(all_raw_items)
    primary_strat = strategies_used[0] if strategies_used else "Multi-Page DOM Extraction"
    return unique_items, primary_strat, current_page


def save_debug_artifacts(page: Optional[Page], log_messages: Optional[List[str]] = None) -> None:
    """Save screenshot, full HTML dump, and logs to debug/ for troubleshooting."""
    try:
        if page:
            page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
            html_content = page.content()
            with open(DEBUG_HTML_PATH, "w", encoding="utf-8") as f:
                f.write(html_content)

        if log_messages:
            with open(DEBUG_LOG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(log_messages))
    except Exception as e:
        logger.error("Failed to save all debug artifacts: %s", e)
