"""Google Collection Media Extractor - Web Application.

A bilingual (Arabic/English) web interface for extracting movie and TV series
titles from Google Collections, enriching them with YTS torrents, magnet links,
Wikipedia/TMDB plot synopses, poster images, and an interactive random watch picker.
"""

import io
import csv
import json
import os
import random
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

import streamlit as st

# Configure page settings
st.set_page_config(
    page_title="CineHarvest - Google Collection Extractor",
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
    except Exception:
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

# --- BILINGUAL TRANSLATIONS ---
TRANSLATIONS = {
    "ar": {
        "page_title": "مستخرج وسائط مجموعات جوجل",
        "app_title": "🎬 مستخرج وسائط مجموعات جوجل (CineHarvest)",
        "app_subtitle": "استخراج تلقائي للأفلام والمسلسلات من أي **قائمة جوجل (Google Collection / Watchlist)** مع جلب **روابط التحميل المباشرة والتورنت (YTS / EZTV)**، **نبذة القصة**، و**صور البوستر الرسمية**.",
        "config_header": "⚙️ الإعدادات والخيارات",
        "lang_select": "🌐 اللغة / Language",
        "fetch_enrichment": "📥 جلب الروابط والبوسترات والقصة",
        "fetch_enrichment_help": "البحث في واجهات YTS و EZTV لجلب روابط التورنت والماغنت، وملخص القصة والصور من ويكيبيديا مجاناً 100%.",
        "tmdb_label": "مفتاح TMDB API (اختياري)",
        "tmdb_help": "لجلب بوسترات 4K فائقة الدقة وتقييمات TMDB الرسمية (اختياري تماماً).",
        "advanced_settings": "🛠️ إعدادات التمرير المتقدمة",
        "max_scrolls": "الحد الأقصى لعدد التمريرات",
        "scroll_delay": "مدة الانتظار بين كل تمريرة (ثوانٍ)",
        "url_label": "رابط مجموعة جوجل القابل للمشاركة (Share Link):",
        "url_placeholder": "https://www.google.com/interests/saved/collection/...",
        "btn_extract": "🚀 بدء الاستخراج",
        "invalid_url": "يرجى إدخال رابط صالح لمجموعة جوجل.",
        "status_title": "جاري استخراج بيانات المجموعة...",
        "status_launching": "🌐 تشغيل متصفح Chromium في الخلفية...",
        "status_navigating": "🔗 فتح رابط المجموعة...",
        "status_scrolling": "📜 تمرير الصفحة لتحميل كافة العناصر...",
        "status_discovered": "📜 تم اكتشاف **{count}** عنصراً حتى الآن...",
        "status_extracting": "🔍 استخراج العناوين، تنظيف البيانات، وإزالة التكرار...",
        "status_enriching": "🎬 جلب روابط التحميل والنبذة التعريفية وصور البوسترات...",
        "status_enrich_progress": "جاري الإثراء: {cur}/{tot} عنصراً",
        "status_tmdb": "✨ الإثراء ببيانات TMDB...",
        "status_complete": "✅ اكتمل الاستخراج والإثراء بنجاح!",
        "status_error": "❌ فشل الاستخراج",
        "metric_discovered": "إجمالي المكتشف",
        "metric_duplicates": "التكرارات المحذوفة",
        "metric_unique": "العناوين الفريدة",
        "metric_strategy": "طريقة الاستخراج",
        "export_header": "📥 تصدير وتنزيل الملفات",
        "btn_txt": "📄 تنزيل TXT",
        "btn_json": "📊 تنزيل JSON",
        "btn_csv": "📑 تنزيل CSV",
        "btn_letterboxd": "🎟️ تنزيل Letterboxd CSV",
        "btn_md": "📝 تنزيل قائمة Markdown",
        "random_box_title": "🎲 حائر ماذا تشاهد؟ اقترح لي عملاً!",
        "random_box_desc": "اضغط الزر أدناه لخلط القائمة واختيار فيلم أو مسلسل عشوائياً مع كامل تفاصيله وروابط تحميله المباشرة.",
        "random_btn": "🎲 اقترح عملاً عشوائياً للمشاهدة الآن!",
        "preview_header": "📋 استعراض القائمة المستخرجة",
        "tab_cards": "🖼️ عرض البطاقات والبوسترات",
        "tab_table": "📊 عرض الجدول الشامل",
        "tab_md": "📝 معاينة قائمة Markdown",
        "download_links": "روابط التحميل المباشرة:",
        "no_downloads": "لا تتوفر روابط تورنت حالياً",
        "view_on_google": "🔗 فتح في جوجل",
        "rating_label": "التقييم",
        "year_label": "السنة",
        "type_label": "النوع",
        "movie": "فيلم",
        "tv": "مسلسل",
        "synopsis_label": "نبذة عن العمل:",
        "filter_type": "تصفية حسب النوع:",
        "all_types": "الكل",
        "search_box": "🔍 بحث في العناوين المستخرجة:",
    },
    "en": {
        "page_title": "Google Collection Media Extractor",
        "app_title": "🎬 Google Collection Media Extractor (CineHarvest)",
        "app_subtitle": "Automatically extract movies and TV shows from any **Google Collection / Watchlist**, enriched with **YTS / EZTV download & magnet links**, **plot synopses**, and **official posters**.",
        "config_header": "⚙️ Configuration",
        "lang_select": "🌐 Language / اللغة",
        "fetch_enrichment": "📥 Fetch Downloads, Synopses & Posters",
        "fetch_enrichment_help": "Searches free YTS & EZTV APIs for torrent/magnet links, and Wikipedia for plot summaries & posters (100% free, no key required).",
        "tmdb_label": "TMDB API Key (Optional)",
        "tmdb_help": "Enriches with official TMDB ratings, 4K posters, and exact metadata (completely optional).",
        "advanced_settings": "🛠️ Advanced Scraper Settings",
        "max_scrolls": "Max Scrolls",
        "scroll_delay": "Scroll Delay (seconds)",
        "url_label": "Google Collection Shareable URL:",
        "url_placeholder": "https://www.google.com/interests/saved/collection/...",
        "btn_extract": "🚀 Start Extraction",
        "invalid_url": "Please enter a valid Google Collection URL.",
        "status_title": "Extracting collection...",
        "status_launching": "🌐 Launching headless Chromium browser...",
        "status_navigating": "🔗 Navigating to collection URL...",
        "status_scrolling": "📜 Scrolling page to load all items...",
        "status_discovered": "📜 Discovered **{count}** items so far...",
        "status_extracting": "🔍 Extracting titles, sanitizing, and deduplicating...",
        "status_enriching": "🎬 Fetching download links, synopses, and posters...",
        "status_enrich_progress": "Enriching: {cur}/{tot} items",
        "status_tmdb": "✨ Enriching with TMDB metadata...",
        "status_complete": "✅ Extraction & Enrichment Complete!",
        "status_error": "❌ Extraction Failed",
        "metric_discovered": "Discovered Items",
        "metric_duplicates": "Duplicates Removed",
        "metric_unique": "Unique Titles",
        "metric_strategy": "Strategy Used",
        "export_header": "📥 Export & Downloads",
        "btn_txt": "📄 Download TXT",
        "btn_json": "📊 Download JSON",
        "btn_csv": "📑 Download CSV",
        "btn_letterboxd": "🎟️ Letterboxd CSV",
        "btn_md": "📝 Markdown Checklist",
        "random_box_title": "🎲 Unsure What to Watch? Pick for Me!",
        "random_box_desc": "Click the button below to shuffle the collection and get an instant recommendation with full synopsis and download buttons.",
        "random_btn": "🎲 Pick a Random Movie / Series to Watch!",
        "preview_header": "📋 Results Preview",
        "tab_cards": "🖼️ Cards & Posters View",
        "tab_table": "📊 Comprehensive Table View",
        "tab_md": "📝 Markdown Preview",
        "download_links": "Direct Downloads:",
        "no_downloads": "No torrents found currently",
        "view_on_google": "🔗 Open in Google",
        "rating_label": "Rating",
        "year_label": "Year",
        "type_label": "Type",
        "movie": "Movie",
        "tv": "TV Series",
        "synopsis_label": "Synopsis:",
        "filter_type": "Filter by type:",
        "all_types": "All",
        "search_box": "🔍 Search titles:",
    },
}

# --- INITIALIZE SESSION STATE ---
if "lang" not in st.session_state:
    st.session_state.lang = "ar"
if "extracted_items" not in st.session_state:
    st.session_state.extracted_items = None
if "extraction_stats" not in st.session_state:
    st.session_state.extraction_stats = None
if "random_pick" not in st.session_state:
    st.session_state.random_pick = None

# --- SIDEBAR CONFIGURATION ---
st.sidebar.header("🌐 CineHarvest")
selected_lang_name = st.sidebar.selectbox(
    "Language / اللغة",
    options=["العربية", "English"],
    index=0 if st.session_state.lang == "ar" else 1,
)
st.session_state.lang = "ar" if selected_lang_name == "العربية" else "en"
t = TRANSLATIONS[st.session_state.lang]

# RTL/LTR Styling
if st.session_state.lang == "ar":
    st.markdown(
        """
        <style>
        .main, .stApp {
            direction: rtl;
            text-align: right;
        }
        /* Keep URLs, code and numbers readable */
        code, pre, .stCodeBlock, input[type="text"] {
            direction: ltr !important;
            text-align: left !important;
        }
        div[data-testid="stMetricValue"] {
            text-align: right !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

st.sidebar.markdown("---")
st.sidebar.header(t["config_header"])

enrich_media = st.sidebar.checkbox(
    t["fetch_enrichment"],
    value=True,
    help=t["fetch_enrichment_help"],
)
tmdb_api_key = st.sidebar.text_input(
    t["tmdb_label"],
    value="",
    type="password",
    help=t["tmdb_help"],
)

with st.sidebar.expander(t["advanced_settings"]):
    max_scrolls = st.slider(t["max_scrolls"], min_value=5, max_value=200, value=MAX_SCROLLS, step=5)
    scroll_delay = st.slider(t["scroll_delay"], min_value=0.5, max_value=4.0, value=SCROLL_DELAY, step=0.25)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "🔗 **GitHub:** [google-collection-extractor](https://github.com/evile92/google-collection-extractor)\n\n"
    "🚀 **Streamlit Cloud Ready**"
)

# --- APP HEADER ---
st.title(t["app_title"])
st.markdown(t["app_subtitle"])

# --- MAIN INPUT SECTION ---
col_input, col_btn = st.columns([4, 1])
with col_input:
    url_input = st.text_input(
        t["url_label"],
        value=DEFAULT_COLLECTION_URL,
        placeholder=t["url_placeholder"],
    )
with col_btn:
    st.write("")
    st.write("")
    start_btn = st.button(t["btn_extract"], type="primary", use_container_width=True)


# --- EXPORT HELPERS ---
def generate_txt(items: List[Dict[str, Any]]) -> str:
    return "\n".join(item.get("title", "").strip() for item in items if item.get("title"))


def generate_json(items: List[Dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)


def generate_csv(items: List[Dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Type", "Year", "Rating", "Synopsis",
        "TorrentURL_1080p", "MagnetLink_1080p", "TorrentURL_720p", "MagnetLink_720p",
        "GoogleURL", "PosterURL"
    ])
    for item in items:
        torrents = item.get("torrents", [])
        t_1080 = next((x for x in torrents if x.get("quality") == "1080p"), None)
        t_720 = next((x for x in torrents if x.get("quality") == "720p"), None)
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
            for tr in torrents[:3]:
                q = tr.get("quality", "HD")
                size = f" ({tr.get('size')})" if tr.get("size") else ""
                if tr.get("magnet"):
                    download_links.append(f"[🧲 Magnet {q}{size}]({tr['magnet']})")
                elif tr.get("url"):
                    download_links.append(f"[📥 Torrent {q}{size}]({tr['url']})")
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


# Helper to render styled HTML badges for magnet/torrent buttons
def render_download_badges(torrents: List[Dict[str, Any]], google_url: Optional[str] = None) -> str:
    badges = []
    if google_url:
        badges.append(
            f'<a href="{google_url}" target="_blank" style="display:inline-block; margin:2px; padding:4px 10px; background:#4b5563; color:white; border-radius:5px; text-decoration:none; font-size:12px;">🔗 Google</a>'
        )
    for tr in torrents[:3]:
        q = tr.get("quality", "HD")
        size = f" ({tr.get('size')})" if tr.get("size") else ""
        if tr.get("magnet"):
            badges.append(
                f'<a href="{tr["magnet"]}" target="_blank" style="display:inline-block; margin:2px; padding:4px 10px; background:#8b5cf6; color:white; border-radius:5px; text-decoration:none; font-size:12px; font-weight:bold;">🧲 {q}{size}</a>'
            )
        elif tr.get("url"):
            badges.append(
                f'<a href="{tr["url"]}" target="_blank" style="display:inline-block; margin:2px; padding:4px 10px; background:#2563eb; color:white; border-radius:5px; text-decoration:none; font-size:12px; font-weight:bold;">📥 Torrent {q}{size}</a>'
            )
    return "".join(badges)


# --- EXTRACTION PROCESS ---
if start_btn:
    if not url_input.strip():
        st.error(t["invalid_url"])
    else:
        status_box = st.status(t["status_title"], expanded=True)
        pw = browser = context = page = None
        try:
            status_box.write(t["status_launching"])
            pw, browser, context, page = launch_browser(headless=True)

            intercepted_items: List[Dict[str, Any]] = []
            setup_network_interception(page, intercepted_items)

            status_box.write(t["status_navigating"])
            open_collection(page, url_input.strip())
            time.sleep(2)

            scroll_placeholder = status_box.empty()
            discovered_counts = []

            def on_progress(count: int):
                discovered_counts.append(count)
                scroll_placeholder.write(t["status_discovered"].format(count=count))

            status_box.write(t["status_scrolling"])
            scroll_until_complete(
                page,
                progress_callback=on_progress,
                scroll_delay=scroll_delay,
                max_scrolls=max_scrolls,
                no_change_limit=NO_CHANGE_LIMIT,
            )

            status_box.write(t["status_extracting"])
            unique_items, strategy_used = extract_collection_data(
                page,
                intercepted_items=intercepted_items,
            )

            if enrich_media and unique_items:
                status_box.write(t["status_enriching"])
                enrich_bar = status_box.progress(0.0)

                def on_enrich(cur: int, tot: int):
                    enrich_bar.progress(cur / tot, text=t["status_enrich_progress"].format(cur=cur, tot=tot))

                unique_items = enrich_media_items(unique_items, progress_callback=on_enrich)
                enrich_bar.empty()

            if tmdb_api_key and tmdb_api_key.strip() and unique_items:
                status_box.write(t["status_tmdb"])
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
            # Pick a default random recommendation when finished
            if unique_items:
                st.session_state.random_pick = random.choice(unique_items)

            status_box.update(label=t["status_complete"], state="complete", expanded=False)

        except ExtractionError as e:
            status_box.update(label=t["status_error"], state="error", expanded=True)
            st.error(f"Extraction Error: {e}")
        except Exception as e:
            status_box.update(label=t["status_error"], state="error", expanded=True)
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

# --- DISPLAY RESULTS & RECOMMENDATIONS ---
if st.session_state.extracted_items is not None:
    items = st.session_state.extracted_items
    stats = st.session_state.extraction_stats

    st.markdown("---")

    # Metrics Row
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(t["metric_discovered"], stats["total"])
    m2.metric(t["metric_duplicates"], stats["duplicates"])
    m3.metric(t["metric_unique"], stats["unique"])
    m4.metric(t["metric_strategy"], stats["strategy"])

    # --- RANDOM WATCH SUGGESTION BOX ---
    st.markdown("---")
    with st.container():
        st.subheader(t["random_box_title"])
        st.caption(t["random_box_desc"])

        col_rand_btn, _ = st.columns([2, 3])
        with col_rand_btn:
            if st.button(t["random_btn"], type="secondary", use_container_width=True):
                st.session_state.random_pick = random.choice(items)

        if st.session_state.random_pick:
            rand_item = st.session_state.random_pick
            with st.container(border=True):
                col_poster, col_info = st.columns([1, 3])

                with col_poster:
                    if rand_item.get("poster_url"):
                        st.image(rand_item["poster_url"], use_container_width=True)
                    else:
                        st.markdown(
                            "<div style='background:#1f2937; height:240px; border-radius:8px; display:flex; align-items:center; justify-content:center; font-size:40px;'>🎬</div>",
                            unsafe_allow_html=True,
                        )

                with col_info:
                    r_type = rand_item.get("type")
                    type_badge = t.get(r_type, r_type.upper() if r_type else "")
                    year_badge = f"({rand_item['year']})" if rand_item.get("year") else ""
                    rating_badge = f"⭐ {rand_item['rating']}/10" if rand_item.get("rating") else ""

                    st.markdown(f"### 🎯 {rand_item.get('title', '')} {year_badge}")
                    st.markdown(f"`{type_badge}` &nbsp;&nbsp; **{rating_badge}**")

                    if rand_item.get("synopsis"):
                        st.info(f"📖 **{t['synopsis_label']}** {rand_item['synopsis']}")

                    # Download and link buttons
                    st.markdown(f"**{t['download_links']}**")
                    torrents = rand_item.get("torrents", [])
                    if torrents:
                        badges_html = render_download_badges(torrents, rand_item.get("url"))
                        st.markdown(badges_html, unsafe_allow_html=True)
                    else:
                        st.caption(t["no_downloads"])
                        if rand_item.get("url"):
                            st.link_button(t["view_on_google"], rand_item["url"])

    # --- EXPORT & DOWNLOADS ROW ---
    st.markdown("---")
    st.subheader(t["export_header"])
    d1, d2, d3, d4, d5 = st.columns(5)

    with d1:
        st.download_button(
            label=t["btn_txt"],
            data=generate_txt(items),
            file_name="collection_titles.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with d2:
        st.download_button(
            label=t["btn_json"],
            data=generate_json(items),
            file_name="collection_data.json",
            mime="application/json",
            use_container_width=True,
        )
    with d3:
        st.download_button(
            label=t["btn_csv"],
            data=generate_csv(items).encode("utf-8-sig"),
            file_name="collection_data.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d4:
        st.download_button(
            label=t["btn_letterboxd"],
            data=generate_letterboxd_csv(items).encode("utf-8-sig"),
            file_name="letterboxd_watchlist.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with d5:
        st.download_button(
            label=t["btn_md"],
            data=generate_markdown(items),
            file_name="collection_watchlist.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # --- RESULTS PREVIEW TABS ---
    st.markdown("---")
    st.subheader(t["preview_header"])

    # Search & Filter controls
    col_filter1, col_filter2 = st.columns([1, 2])
    with col_filter1:
        type_options = [t["all_types"], t["movie"], t["tv"]]
        filter_val = st.selectbox(t["filter_type"], options=type_options, index=0)
    with col_filter2:
        search_query = st.text_input(t["search_box"], value="", placeholder="e.g. Inception, Breaking Bad...")

    # Filter items
    filtered_items = items
    if filter_val == t["movie"]:
        filtered_items = [x for x in filtered_items if x.get("type") == "movie"]
    elif filter_val == t["tv"]:
        filtered_items = [x for x in filtered_items if x.get("type") == "tv"]

    if search_query.strip():
        q = search_query.strip().lower()
        filtered_items = [x for x in filtered_items if q in x.get("title", "").lower()]

    tab_cards, tab_table, tab_md = st.tabs([t["tab_cards"], t["tab_table"], t["tab_md"]])

    # 1. Cards View with Posters
    with tab_cards:
        if not filtered_items:
            st.info("No matching items found.")
        else:
            # Display items in responsive 3-column cards
            num_cols = 3
            for i in range(0, len(filtered_items), num_cols):
                chunk = filtered_items[i : i + num_cols]
                cols = st.columns(num_cols)
                for col_idx, it in enumerate(chunk):
                    with cols[col_idx]:
                        with st.container(border=True):
                            if it.get("poster_url"):
                                st.image(it["poster_url"], use_container_width=True)
                            else:
                                st.markdown(
                                    "<div style='background:#1f2937; height:200px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:36px;'>🎬</div>",
                                    unsafe_allow_html=True,
                                )

                            title_str = it.get("title", "")
                            year_str = f" ({it['year']})" if it.get("year") else ""
                            rating_str = f"⭐ {it['rating']}" if it.get("rating") else ""
                            st.markdown(f"**{title_str}** {year_str}")

                            c_type = it.get("type")
                            badge_text = t.get(c_type, c_type.upper() if c_type else "")
                            st.caption(f"`{badge_text}` {rating_str}")

                            if it.get("synopsis"):
                                short_syn = it["synopsis"][:120] + ("..." if len(it["synopsis"]) > 120 else "")
                                st.markdown(f"<small>{short_syn}</small>", unsafe_allow_html=True)

                            it_torrents = it.get("torrents", [])
                            badges_html = render_download_badges(it_torrents, it.get("url"))
                            if badges_html:
                                st.markdown(badges_html, unsafe_allow_html=True)

    # 2. Table View
    with tab_table:
        table_rows = []
        for it in filtered_items:
            it_torrents = it.get("torrents", [])
            has_magnet = bool(it_torrents and it_torrents[0].get("magnet"))
            table_rows.append({
                "Title": it.get("title", ""),
                "Type": it.get("type") or "-",
                "Year": it.get("year") or "-",
                "Rating": f"⭐ {it['rating']}" if it.get("rating") else "-",
                "Synopsis": (it.get("synopsis")[:90] + "...") if it.get("synopsis") else "-",
                "Downloads": f"🧲 {len(it_torrents)} links" if has_magnet else ("📥 Available" if it_torrents else "-"),
                "Google URL": it.get("url") or "-",
            })
        st.dataframe(table_rows, use_container_width=True)

    # 3. Markdown Checklist View
    with tab_md:
        st.markdown(generate_markdown(filtered_items))
