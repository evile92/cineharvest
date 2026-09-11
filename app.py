"""Google Collection Extractor - Web Application.

Provides a live web interface for extracting movie and TV series titles
from Google Collections, enriching them with YTS torrents, magnet links,
and plot synopses, and offering instant downloads in multiple formats.
"""

import io
import csv
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple

import streamlit as st

# Configure page settings
st.set_page_config(
    page_title="Google Collection Extractor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def ensure_playwright_browsers() -> None:
    """Ensure Chromium browser binary is installed in Linux/Cloud container."""
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as e:
        # If already installed or warning, continue
        pass


ensure_playwright_browsers()

from config import (
    DEFAULT_COLLECTION_URL,
    MAX_SCROLLS,
    SCROLL_DELAY,
    NO_CHANGE_LIMIT,
)
from extractor import (
    launch_browser,
    open_collection,
    scroll_until_complete,
    extract_collection_data,
    setup_network_interception,
    ExtractionError,
)
from media_enricher import enrich_media_items
from tmdb import enrich_items_with_tmdb


def generate_txt(items: List[Dict[str, Any]]) -> str:
    """Generate clean TXT string with one title per line."""
    return "\n".join(item.get("title", "").strip() for item in items if item.get("title"))


def generate_json(items: List[Dict[str, Any]]) -> str:
    """Generate pretty-printed JSON string."""
    return json.dumps(items, ensure_ascii=False, indent=2)


def generate_csv(items: List[Dict[str, Any]]) -> str:
    """Generate detailed CSV with synopsis and torrent links."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Type", "Year", "Rating", "Synopsis",
        "TorrentURL_1080p", "MagnetLink_1080p", "TorrentURL_720p", "MagnetLink_720p",
        "GoogleURL", "PosterURL"
    ])
    for item in items:
        torrents = item.get("torrents", [])
        t_1080 = next((t for t in torrents if t.get("quality") == "1080p"), None)
        t_720 = next((t for t in torrents if t.get("quality") == "720p"), None)
        if not t_1080 and torrents:
            t_1080 = torrents[0]

        writer.writerow([
            item.get("title", ""),
            item.get("type") or "",
            item.get("year") or "",
            item.get("rating") or "",
            item.get("synopsis") or "",
            t_1080.get("url") if t_1080 else "",
            t_1080.get("magnet") if t_1080 else "",
            t_720.get("url") if t_720 else "",
            t_720.get("magnet") if t_720 else "",
            item.get("url") or "",
            item.get("poster_url") or "",
        ])
    return output.getvalue()


def generate_letterboxd_csv(items: List[Dict[str, Any]]) -> str:
    """Generate Letterboxd import CSV (Title, Year, URL)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Title", "Year", "URL"])
    for item in items:
        writer.writerow([
            item.get("title", ""),
            item.get("year") or "",
            item.get("url") or "",
        ])
    return output.getvalue()


def generate_markdown(items: List[Dict[str, Any]], collection_title: str = "Google Watchlist") -> str:
    """Generate formatted Markdown checklist with synopsis and download links."""
    lines = [
        f"# {collection_title}",
        "",
        f"> Extracted {len(items)} items using Google Collection Media Extractor.",
        "",
        "## Watchlist Checklist & Downloads",
        "",
    ]
    for item in items:
        title = item.get("title", "")
        url = item.get("url")
        year_str = f" ({item['year']})" if item.get("year") else ""
        rating_str = f" ⭐ {item['rating']}/10" if item.get("rating") else ""
        type_str = f" `[{item['type']}]`" if item.get("type") else ""

        link_title = f"[{title}]({url})" if url else title
        lines.append(f"- [ ] **{link_title}**{year_str}{type_str}{rating_str}")

        synopsis = item.get("synopsis")
        if synopsis:
            short_syn = synopsis[:280] + ("..." if len(synopsis) > 280 else "")
            lines.append(f"  > 📖 *{short_syn}*")

        torrents = item.get("torrents", [])
        if torrents:
            download_links = []
            for t in torrents[:3]:
                q = t.get("quality", "HD")
                size = f" ({t.get('size')})" if t.get("size") else ""
                if t.get("magnet"):
                    download_links.append(f"[🧲 Magnet {q}{size}]({t['magnet']})")
                elif t.get("url"):
                    download_links.append(f"[📥 Torrent {q}{size}]({t['url']})")
            if download_links:
                lines.append(f"  > 💾 **Downloads:** {' | '.join(download_links)}")
        lines.append("")

    lines.extend([
        "## Detailed Table",
        "",
        "| # | Title | Type | Year | Rating | Links |",
        "|---|---|---|---|---|---|",
    ])
    for idx, item in enumerate(items, 1):
        title = item.get("title", "")
        media_type = item.get("type") or "-"
        year = item.get("year") or "-"
        rating = f"⭐ {item['rating']}" if item.get("rating") else "-"
        url = item.get("url")
        actions = []
        if url:
            actions.append(f"[Google]({url})")
        torrents = item.get("torrents", [])
        if torrents and torrents[0].get("magnet"):
            actions.append(f"[🧲 Magnet]({torrents[0]['magnet']})")
        actions_str = " \\| ".join(actions) if actions else "-"
        lines.append(f"| {idx} | **{title}** | `{media_type}` | {year} | {rating} | {actions_str} |")

    return "\n".join(lines)


# --- UI HEADER ---
st.title("🎬 Google Collection Media Extractor")
st.markdown(
    "Extract movies & TV shows from any public **Google Saved Collection**, "
    "automatically enrich with **YTS / EZTV download links** & **plot summaries**, "
    "and export to **TXT, JSON, CSV, Letterboxd, and Markdown**."
)

# --- SIDEBAR SETTINGS ---
st.sidebar.header("⚙️ Configuration")
enrich_media = st.sidebar.checkbox(
    "Fetch Downloads & Synopses",
    value=True,
    help="Queries free YTS/EZTV APIs for torrent/magnet links and Wikipedia for plot summaries.",
)
tmdb_api_key = st.sidebar.text_input(
    "TMDB API Key (Optional)",
    value="",
    type="password",
    help="Optional TMDB API key to enrich with official ratings, posters, and release years.",
)

with st.sidebar.expander("🛠️ Advanced Scraper Settings"):
    max_scrolls = st.slider("Max Scrolls", min_value=5, max_value=200, value=MAX_SCROLLS, step=5)
    scroll_delay = st.slider("Scroll Delay (seconds)", min_value=0.5, max_value=4.0, value=SCROLL_DELAY, step=0.25)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "🔗 **GitHub:** [google-collection-extractor](https://github.com/evile92/google-collection-extractor)\n\n"
    "💡 *Deployable for free on Streamlit Community Cloud.*"
)

# --- MAIN INPUT ---
col_input, col_btn = st.columns([4, 1])
with col_input:
    url_input = st.text_input(
        "Google Collection Shareable URL:",
        value=DEFAULT_COLLECTION_URL,
        placeholder="https://www.google.com/interests/saved/collection/...",
    )
with col_btn:
    st.write("")
    st.write("")
    start_btn = st.button("🚀 Extract", type="primary", use_container_width=True)

# Session State for caching results across re-renders
if "extracted_items" not in st.session_state:
    st.session_state.extracted_items = None
if "extraction_stats" not in st.session_state:
    st.session_state.extraction_stats = None

if start_btn:
    if not url_input.strip():
        st.error("Please enter a valid Google Collection URL.")
    else:
        status_box = st.status("Extracting collection...", expanded=True)
        pw = browser = context = page = None
        try:
            status_box.write("🌐 Launching headless Chromium browser...")
            pw, browser, context, page = launch_browser(headless=True)

            intercepted_items: List[Dict[str, Any]] = []
            setup_network_interception(page, intercepted_items)

            status_box.write("🔗 Navigating to collection URL...")
            open_collection(page, url_input.strip())
            time.sleep(2)

            scroll_placeholder = status_box.empty()
            discovered_counts = []

            def on_progress(count: int):
                discovered_counts.append(count)
                scroll_placeholder.write(f"📜 Discovered **{count}** items during scroll...")

            status_box.write("📜 Scrolling page to load full collection...")
            scroll_until_complete(
                page,
                progress_callback=on_progress,
                scroll_delay=scroll_delay,
                max_scrolls=max_scrolls,
                no_change_limit=NO_CHANGE_LIMIT,
            )

            status_box.write("🔍 Extracting titles and cleaning data...")
            unique_items, strategy_used = extract_collection_data(
                page,
                intercepted_items=intercepted_items,
            )

            if enrich_media and unique_items:
                status_box.write("🎬 Fetching download links (YTS / EZTV) and plot summaries...")
                enrich_bar = status_box.progress(0.0)

                def on_enrich(cur: int, tot: int):
                    enrich_bar.progress(cur / tot, text=f"Enriching: {cur}/{tot} items")

                unique_items = enrich_media_items(unique_items, progress_callback=on_enrich)
                enrich_bar.empty()

            if tmdb_api_key and tmdb_api_key.strip() and unique_items:
                status_box.write("✨ Enriching with TMDB metadata...")
                unique_items = enrich_items_with_tmdb(unique_items, tmdb_api_key.strip())

            total_discovered = discovered_counts[-1] if discovered_counts else len(unique_items)
            duplicates_count = max(0, total_discovered - len(unique_items))

            st.session_state.extracted_items = unique_items
            st.session_state.extraction_stats = {
                "total": total_discovered,
                "duplicates": duplicates_count,
                "unique": len(unique_items),
                "strategy": strategy_used,
            }
            status_box.update(label="✅ Extraction Complete!", state="complete", expanded=False)

        except ExtractionError as e:
            status_box.update(label="❌ Extraction Failed", state="error", expanded=True)
            st.error(f"Extraction Error: {e}")
        except Exception as e:
            status_box.update(label="❌ Unexpected Error", state="error", expanded=True)
            st.error(f"An unexpected error occurred: {e}")
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

# --- DISPLAY RESULTS ---
if st.session_state.extracted_items is not None:
    items = st.session_state.extracted_items
    stats = st.session_state.extraction_stats

    st.markdown("---")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Discovered Items", stats["total"])
    m2.metric("Duplicates Removed", stats["duplicates"])
    m3.metric("Unique Titles", stats["unique"])
    m4.metric("Strategy Used", stats["strategy"])

    st.subheader("📥 Export & Downloads")
    d1, d2, d3, d4, d5 = st.columns(5)

    with d1:
        st.download_button(
            label="📄 Download TXT",
            data=generate_txt(items),
            file_name="collection_titles.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            label="📊 Download JSON",
            data=generate_json(items),
            file_name="collection_data.json",
            mime="application/json",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            label="📑 Download CSV",
            data=generate_csv(items).encode("utf-8-sig"),
            file_name="collection_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d4:
        st.download_button(
            label="🎟️ Letterboxd CSV",
            data=generate_letterboxd_csv(items).encode("utf-8-sig"),
            file_name="letterboxd_watchlist.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d5:
        st.download_button(
            label="📝 Markdown Checklist",
            data=generate_markdown(items),
            file_name="collection_watchlist.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # Preview Tabs
    st.subheader("📋 Results Preview")
    tab_table, tab_md = st.tabs(["📊 Table View", "📝 Markdown Preview"])

    with tab_table:
        table_rows = []
        for it in items:
            torrents = it.get("torrents", [])
            has_magnet = bool(torrents and torrents[0].get("magnet"))
            table_rows.append({
                "Title": it.get("title", ""),
                "Type": it.get("type") or "unknown",
                "Year": it.get("year") or "-",
                "Rating": f"⭐ {it['rating']}" if it.get("rating") else "-",
                "Synopsis": (it.get("synopsis")[:100] + "...") if it.get("synopsis") else "-",
                "Downloads": f"🧲 {len(torrents)} links" if has_magnet else ("📥 Available" if torrents else "-"),
            })
        st.dataframe(table_rows, use_container_width=True)

    with tab_md:
        st.markdown(generate_markdown(items))
