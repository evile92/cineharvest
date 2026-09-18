"""Google Collection Media Extractor & Universal Search (CineHarvest).

A bilingual (Arabic/English) web application for:
1. Extracting movies & TV shows from public Google Collections/Watchlists.
2. Direct database search across YTS, Wikipedia, and TMDB by title.
3. Automatic enrichment with posters, magnet/torrent links, and bilingual (AR/EN) synopses.
4. Interactive random watch recommendations.
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
    page_title="CineHarvest - Media Extractor & Movie Search",
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
try:
    from extractor import (
        launch_browser,
        open_collection,
        scroll_until_complete,
        extract_collection_data,
        extract_all_collection_pages,
        setup_network_interception,
        ExtractionError,
    )
    PLAYWRIGHT_AVAILABLE = True
    PLAYWRIGHT_IMPORT_ERROR = None
except Exception as _pe_err:
    PLAYWRIGHT_AVAILABLE = False
    PLAYWRIGHT_IMPORT_ERROR = str(_pe_err)
    launch_browser = None
    open_collection = None
    scroll_until_complete = None
    extract_collection_data = None
    extract_all_collection_pages = None
    setup_network_interception = None

    class ExtractionError(Exception):
        """Fallback ExtractionError when extractor cannot be imported."""
        pass

from media_enricher import enrich_media_items, search_media_database
from cleaner import generate_markdown, GENRE_ICONS, GENRE_ARABIC
from tmdb import enrich_items_with_tmdb
from youtube_downloader import (
    extract_media_info,
    download_single_video,
    download_playlist_media,
    is_playlist_url,
)

# --- BILINGUAL TRANSLATIONS ---
TRANSLATIONS = {
    "en": {
        "page_title": "CineHarvest - Media Extractor & Movie Search",
        "app_title": "🎬 CineHarvest - Media Extractor & Search",
        "app_subtitle": "Universal entertainment hub: extract from **Google Watchlists** or **search any movie/series directly** to get official posters, plot synopses (Arabic & English), and high-speed **Magnet & Torrent download links**.",
        "nav_header": "🧭 Navigation & Mode",
        "mode_label": "Select Feature:",
        "mode_collection": "📂 Google Collection Extractor",
        "mode_search": "🔍 Direct Movie & Series Search",
        "mode_youtube": "📺 YouTube Downloader (Video & Playlist)",
        "config_header": "⚙️ Configuration",
        "lang_select": "🌐 Language / اللغة",
        "fetch_enrichment": "📥 Fetch Downloads, Synopses & Posters",
        "fetch_enrichment_help": "Queries free YTS & EZTV APIs for torrent/magnet links, and Wikipedia for bilingual plot synopses and posters.",
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
        "status_discovered": "📜 Discovered **{count}** items on this page...",
        "status_page_progress": "📄 Processing page **{page}**... ({count} items accumulated so far)",
        "status_moving_next_page": "➡️ Multi-page collection detected: Moving to page {next_page}...",
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
        "preview_header": "📋 Collection Results",
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
        "genre_label": "Genre",
        "filter_genre": "Filter by Genre:",
        "all_genres": "All Genres",
        "search_box": "🔍 Search within extracted titles:",
        # Direct Search Feature
        "direct_search_title": "🔍 Search Movies & TV Series Database",
        "direct_search_desc": "Search by title to fetch official posters, plot synopses (Arabic & English), and direct Magnet & Torrent download links.",
        "direct_input_label": "Movie or Series Name:",
        "direct_input_placeholder": "e.g. Interstellar, Oppenheimer, Breaking Bad, Gladiator...",
        "btn_direct_search": "🔍 Search Database",
        "direct_status_searching": "Searching free databases (YTS, Wikipedia, EZTV)...",
        "direct_results_count": "Found **{count}** matching results:",
        "direct_no_results": "No results found for this title. Try a different spelling or keyword.",
        # YouTube Downloader Feature
        "yt_title": "📺 YouTube Media Downloader",
        "yt_subtitle": "Download single YouTube videos or entire playlists in audio (MP3 320k/192k/128k, M4A, WAV) or video (MP4 up to 1080p).",
        "yt_url_label": "YouTube Video or Playlist URL:",
        "yt_url_placeholder": "https://www.youtube.com/watch?v=... or https://www.youtube.com/playlist?list=...",
        "yt_btn_inspect": "🔍 Fetch & Preview",
        "yt_fetching_info": "Fetching video/playlist metadata from YouTube...",
        "yt_invalid_url": "Please enter a valid YouTube video or playlist URL.",
        "yt_error_fetching": "Failed to retrieve information from YouTube: {err}",
        "yt_playlist_badge": "Playlist ({count} videos)",
        "yt_video_badge": "Single Video",
        "yt_uploader": "Channel / Creator:",
        "yt_duration": "Duration:",
        "yt_views": "Views:",
        "yt_playlist_items": "Playlist Tracks & Videos Selection",
        "yt_select_all": "Select All Videos",
        "yt_download_options": "⚙️ Download Settings",
        "yt_media_type": "Desired Media Format:",
        "yt_type_audio": "🎵 Audio Only (MP3 / M4A / WAV)",
        "yt_type_video": "🎬 Full Video (MP4)",
        "yt_audio_format": "Audio Container:",
        "yt_audio_quality": "Audio Bitrate / Quality:",
        "yt_video_quality": "Video Resolution:",
        "yt_btn_start_download": "🚀 Start Download",
        "yt_downloading": "Downloading and processing media with FFmpeg...",
        "yt_downloading_item": "Downloading track {cur}/{tot}: {title}",
        "yt_download_complete": "✅ Download complete! Click below to save to your device:",
        "yt_btn_save_file": "💾 Save Media File",
        "yt_btn_save_zip": "📦 Save Playlist ZIP Archive",
    },
    "ar": {
        "page_title": "CineHarvest - مستخرج وسائط وباحث الأفلام",
        "app_title": "🎬 CineHarvest - مستخرج وباحث الأفلام والمسلسلات",
        "app_subtitle": "منصة وسائط متكاملة: استخراج أفلام ومسلسلات من **قوائم جوجل (Google Watchlists)** أو **البحث المباشر بالاسم عن أي فيلم أو مسلسل** مع البوسترات الرسمية، ملخص القصة (باللغة العربية والإنجليزية)، و**روابط التحميل والتورنت المباشرة**.",
        "nav_header": "🧭 التنقل والأوضاع",
        "mode_label": "اختر وضع العمل:",
        "mode_collection": "📂 استخراج مجموعات جوجل (Google Collections)",
        "mode_search": "🔍 البحث المباشر في قواعد البيانات (Direct Search)",
        "mode_youtube": "📺 تحميل من يوتيوب (فيديو وقوائم تشغيل)",
        "config_header": "⚙️ الإعدادات والخيارات",
        "lang_select": "🌐 اللغة / Language",
        "fetch_enrichment": "📥 جلب الروابط والبوسترات والقصة",
        "fetch_enrichment_help": "البحث في واجهات YTS و EZTV لجلب روابط التورنت والماغنت، وملخص القصة العربي والإنجليزي من ويكيبيديا مجاناً.",
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
        "status_scrolling": "📜 جاري التمرير الذكي لجلب كافة عناصر الصفحة...",
        "status_discovered": "📜 تم اكتشاف **{count}** عنصراً في هذه الصفحة...",
        "status_page_progress": "📄 معالجة الصفحة **{page}**... (تم جمع {count} عنصراً حتى الآن)",
        "status_moving_next_page": "➡️ تم اكتشاف قائمة متعددة الصفحات: الانتقال للصفحة {next_page}...",
        "status_extracting": "🔍 استخراج العناوين والتحقق منها وحذف التكرارات...",
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
        "genre_label": "التصنيف الفني",
        "filter_genre": "تصفية حسب التصنيف الفني:",
        "all_genres": "جميع التصنيفات",
        "search_box": "🔍 بحث في العناوين المستخرجة:",
        # Direct Search Feature
        "direct_search_title": "🔍 البحث في قواعد بيانات الأفلام والمسلسلات",
        "direct_search_desc": "ابحث بالاسم عن أي فيلم أو مسلسل لجلب البوستر الرسمي، ملخص القصة بالعربية، وروابط تحميل Magnet و Torrent مباشرة.",
        "direct_input_label": "اسم الفيلم أو المسلسل:",
        "direct_input_placeholder": "مثال: Interstellar, Oppenheimer, Breaking Bad, Gladiator...",
        "btn_direct_search": "🔍 ابحث في قواعد البيانات",
        "direct_status_searching": "جاري البحث في قواعد البيانات المجانية (YTS, Wikipedia, EZTV)...",
        "direct_results_count": "تم العثور على **{count}** نتيجة مطابقة:",
        "direct_no_results": "لم يتم العثور على نتائج مطابقة لهذا العنوان. جرب كتابة اسم العمل بالإنجليزية.",
        # YouTube Downloader Feature
        "yt_title": "📺 أداة تحميل الوسائط من يوتيوب",
        "yt_subtitle": "تحميل فيديوهات يوتيوب الفردية أو قوائم التشغيل (Playlists) بالكامل بصوت MP3 (حتى 320kbps) أو M4A أو WAV، أو فيديو MP4 بدقة تصل إلى 1080p.",
        "yt_url_label": "رابط الفيديو أو قائمة التشغيل (Playlist):",
        "yt_url_placeholder": "https://www.youtube.com/watch?v=... أو https://www.youtube.com/playlist?list=...",
        "yt_btn_inspect": "🔍 جلب ومعاينة الرابط",
        "yt_fetching_info": "جاري استخراج بيانات ومعلومات الرابط من يوتيوب...",
        "yt_invalid_url": "يرجى إدخال رابط يوتيوب صحيح لفيديو أو قائمة تشغيل.",
        "yt_error_fetching": "تعذر جلب معلومات الرابط من يوتيوب: {err}",
        "yt_playlist_badge": "قائمة تشغيل ({count} فيديو)",
        "yt_video_badge": "فيديو فردي",
        "yt_uploader": "القناة / الناشر:",
        "yt_duration": "المدة:",
        "yt_views": "المشاهدات:",
        "yt_playlist_items": "تحديد عناصر وفيديوهات قائمة التشغيل",
        "yt_select_all": "تحديد كافة الفيديوهات",
        "yt_download_options": "⚙️ خيارات وإعدادات التحميل",
        "yt_media_type": "نوع الوسائط المطلوب:",
        "yt_type_audio": "🎵 صوت فقط (MP3 / M4A / WAV)",
        "yt_type_video": "🎬 فيديو كامل (MP4)",
        "yt_audio_format": "صيغة الصوت:",
        "yt_audio_quality": "جودة ومعدل البت للصوت (Bitrate):",
        "yt_video_quality": "دقة وجودة الفيديو:",
        "yt_btn_start_download": "🚀 بدء التحميل الآن",
        "yt_downloading": "جاري التحميل والمعالجة وتحويل الصيغ بواسطة FFmpeg...",
        "yt_downloading_item": "جاري تحميل المقطع {cur}/{tot}: {title}",
        "yt_download_complete": "✅ اكتمل التحميل والمعالجة بنجاح! اضغط الزر أدناه لحفظ الملف:",
        "yt_btn_save_file": "💾 حفظ الملف المحمل",
        "yt_btn_save_zip": "📦 حفظ قائمة التشغيل (ملف ZIP مضغوط)",
    },
}

# --- INITIALIZE SESSION STATE ---
if "lang" not in st.session_state:
    st.session_state.lang = "en"
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "collection"
if "extracted_items" not in st.session_state:
    st.session_state.extracted_items = None
if "extraction_stats" not in st.session_state:
    st.session_state.extraction_stats = None
if "random_pick" not in st.session_state:
    st.session_state.random_pick = None
if "direct_search_results" not in st.session_state:
    st.session_state.direct_search_results = None
if "yt_info" not in st.session_state:
    st.session_state.yt_info = None
if "yt_downloaded_data" not in st.session_state:
    st.session_state.yt_downloaded_data = None
if "yt_download_filename" not in st.session_state:
    st.session_state.yt_download_filename = None
if "yt_is_zip" not in st.session_state:
    st.session_state.yt_is_zip = False

# --- SIDEBAR CONFIGURATION ---
st.sidebar.header("🌐 CineHarvest")
selected_lang_name = st.sidebar.selectbox(
    "Language / اللغة",
    options=["English", "العربية"],
    index=0 if st.session_state.lang == "en" else 1,
)
st.session_state.lang = "en" if selected_lang_name == "English" else "ar"
t = TRANSLATIONS[st.session_state.lang]

# Navigation Mode Selection
st.sidebar.markdown("---")
st.sidebar.subheader(t["nav_header"])
mode_options = [t["mode_collection"], t["mode_search"], t["mode_youtube"]]
mode_idx = 0
if st.session_state.app_mode == "search":
    mode_idx = 1
elif st.session_state.app_mode == "youtube":
    mode_idx = 2

mode_selection = st.sidebar.radio(
    t["mode_label"],
    options=mode_options,
    index=mode_idx,
)
if mode_selection == t["mode_collection"]:
    st.session_state.app_mode = "collection"
elif mode_selection == t["mode_search"]:
    st.session_state.app_mode = "search"
else:
    st.session_state.app_mode = "youtube"

# RTL/LTR Dynamic Responsive Styling
if st.session_state.lang == "ar":
    st.markdown(
        """
        <style>
        /* Global Root & Containers */
        html, body, [data-testid="stAppViewContainer"], .main, .stApp {
            direction: rtl !important;
            text-align: right !important;
        }

        /* Sidebar RTL */
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] div,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label {
            direction: rtl !important;
            text-align: right !important;
        }

        /* Headings & Text */
        h1, h2, h3, h4, h5, h6,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            direction: rtl !important;
            text-align: right !important;
        }

        /* Form Controls & Labels */
        label,
        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] *,
        [data-testid="stRadio"] label,
        [data-testid="stCheckbox"] label {
            direction: rtl !important;
            text-align: right !important;
        }

        /* Metrics & Status Cards */
        [data-testid="stMetric"],
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"],
        [data-testid="stMetric"] * {
            text-align: right !important;
            direction: rtl !important;
            justify-content: flex-end !important;
        }

        /* Alerts & Info callouts */
        [data-testid="stAlert"],
        [data-testid="stAlert"] * {
            direction: rtl !important;
            text-align: right !important;
        }

        /* Tabs list alignment */
        [data-baseweb="tab-list"] {
            direction: rtl !important;
        }

        /* Keep code, URLs, and inputs LTR */
        input[type="text"],
        input[type="password"],
        code,
        pre,
        .stCodeBlock {
            direction: ltr !important;
            text-align: left !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        """
        <style>
        /* Global Root & Containers LTR */
        html, body, [data-testid="stAppViewContainer"], .main, .stApp {
            direction: ltr !important;
            text-align: left !important;
        }

        /* Sidebar LTR */
        [data-testid="stSidebar"],
        [data-testid="stSidebar"] div,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] label {
            direction: ltr !important;
            text-align: left !important;
        }

        /* Headings & Text LTR */
        h1, h2, h3, h4, h5, h6,
        [data-testid="stMarkdownContainer"],
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stCaptionContainer"],
        [data-testid="stCaptionContainer"] p {
            direction: ltr !important;
            text-align: left !important;
        }

        /* Form Controls & Labels LTR */
        label,
        [data-testid="stWidgetLabel"],
        [data-testid="stWidgetLabel"] * {
            direction: ltr !important;
            text-align: left !important;
        }

        /* Metrics LTR */
        [data-testid="stMetric"],
        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"],
        [data-testid="stMetric"] * {
            text-align: left !important;
            direction: ltr !important;
            justify-content: flex-start !important;
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
    "🚀 **Live at:** [cineharvest.streamlit.app](https://cineharvest.streamlit.app)"
)

# --- APP HEADER ---
st.title(t["app_title"])
st.markdown(t["app_subtitle"])


# Helper to get synopsis in the user's selected language
def get_synopsis_text(item: Dict[str, Any], lang: str) -> Optional[str]:
    if lang == "ar":
        return item.get("synopsis_ar") or item.get("synopsis")
    return item.get("synopsis") or item.get("synopsis_ar")


# Helper to render styled HTML badges for magnet/torrent buttons
def render_download_badges(torrents: List[Dict[str, Any]], google_url: Optional[str] = None) -> str:
    badges = []
    if google_url:
        badges.append(
            f'<a href="{google_url}" target="_blank" style="display:inline-block; margin:2px; padding:4px 10px; background:#4b5563; color:white; border-radius:5px; text-decoration:none; font-size:12px;">🔗 Link</a>'
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


def format_duration(seconds: Optional[int]) -> str:
    """Format duration in seconds to MM:SS or HH:MM:SS format."""
    if not seconds:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_file_size(size_bytes: Optional[int]) -> str:
    """Format bytes into readable string (KB, MB, GB)."""
    if not size_bytes or size_bytes <= 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# Export Helpers
def generate_txt(items: List[Dict[str, Any]]) -> str:
    return "\n".join(item.get("title", "").strip() for item in items if item.get("title"))


def generate_json(items: List[Dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False, indent=2)


def generate_csv(items: List[Dict[str, Any]], lang: str = "en") -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Type", "Genres", "Year", "Rating", "Synopsis", "Synopsis_AR",
        "TorrentURL_1080p", "MagnetLink_1080p", "TorrentURL_720p", "MagnetLink_720p",
        "GoogleURL", "PosterURL"
    ])
    # Group and sort: Movies first, TV series second, then by genre and title
    sorted_items = sorted(
        items,
        key=lambda x: (
            0 if x.get("type") != "tv" else 1,
            x.get("primary_genre") or (x.get("genres", ["Other"])[0] if x.get("genres") else "Other"),
            x.get("title", "").lower()
        )
    )
    for item in sorted_items:
        torrents = item.get("torrents", [])
        t_1080 = next((x for x in torrents if x.get("quality") == "1080p"), None)
        t_720 = next((x for x in torrents if x.get("quality") == "720p"), None)
        if not t_1080 and torrents:
            t_1080 = torrents[0]

        genres_str = ", ".join(item.get("genres", [])) if item.get("genres") else (item.get("primary_genre") or "")

        writer.writerow([
            item.get("title", ""),
            item.get("type") or "",
            genres_str,
            item.get("year") or "",
            item.get("rating") or "",
            item.get("synopsis") or "",
            item.get("synopsis_ar") or "",
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


# ==============================================================================
# MODE 1: GOOGLE COLLECTION EXTRACTOR
# ==============================================================================
if st.session_state.app_mode == "collection":
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

    if start_btn:
        if not url_input.strip():
            st.error(t["invalid_url"])
        elif not PLAYWRIGHT_AVAILABLE:
            st.error(f"Playwright automation engine is not available in this environment: {PLAYWRIGHT_IMPORT_ERROR}")
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

                page_placeholder = status_box.empty()
                scroll_placeholder = status_box.empty()
                discovered_counts = []

                def on_page_progress(page_num: int, count_so_far: int):
                    page_placeholder.write(t["status_page_progress"].format(page=page_num, count=count_so_far))

                def on_progress(count: int):
                    discovered_counts.append(count)
                    scroll_placeholder.write(t["status_discovered"].format(count=count))

                status_box.write(t["status_scrolling"])
                unique_items, strategy_used, total_pages = extract_all_collection_pages(
                    page,
                    intercepted_items=intercepted_items,
                    page_callback=on_page_progress,
                    scroll_callback=on_progress,
                    scroll_delay=scroll_delay,
                    max_scrolls=max_scrolls,
                    no_change_limit=NO_CHANGE_LIMIT,
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

                total_discovered = max(len(unique_items), discovered_counts[-1] if discovered_counts else len(unique_items))
                duplicates_count = max(0, total_discovered - len(unique_items))

                strategy_display = f"{strategy_used} ({total_pages} pages)" if total_pages > 1 else strategy_used

                st.session_state.extracted_items = unique_items
                st.session_state.extraction_stats = {
                    "total": total_discovered,
                    "duplicates": duplicates_count,
                    "unique": len(unique_items),
                    "strategy": strategy_display,
                    "pages": total_pages,
                }
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

    # Results view for collection
    if st.session_state.extracted_items is not None:
        items = st.session_state.extracted_items
        stats = st.session_state.extraction_stats

        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(t["metric_discovered"], stats["total"])
        m2.metric(t["metric_duplicates"], stats["duplicates"])
        m3.metric(t["metric_unique"], stats["unique"])
        m4.metric(t["metric_strategy"], stats["strategy"])

        # Random Recommendation
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
                        p_genre = rand_item.get("primary_genre") or (rand_item.get("genres", [None])[0] if rand_item.get("genres") else None)
                        genre_disp = f" • {GENRE_ICONS.get(p_genre, '')} {GENRE_ARABIC.get(p_genre, p_genre) if st.session_state.lang == 'ar' else p_genre}" if p_genre else ""
                        year_badge = f"({rand_item['year']})" if rand_item.get("year") else ""
                        rating_badge = f"⭐ {rand_item['rating']}/10" if rand_item.get("rating") else ""

                        st.markdown(f"### 🎯 {rand_item.get('title', '')} {year_badge}")
                        st.markdown(f"`{type_badge}`{genre_disp} &nbsp;&nbsp; **{rating_badge}**")

                        item_syn = get_synopsis_text(rand_item, st.session_state.lang)
                        if item_syn:
                            st.info(f"📖 **{t['synopsis_label']}** {item_syn}")

                        st.markdown(f"**{t['download_links']}**")
                        torrents = rand_item.get("torrents", [])
                        if torrents:
                            badges_html = render_download_badges(torrents, rand_item.get("url"))
                            st.markdown(badges_html, unsafe_allow_html=True)
                        else:
                            st.caption(t["no_downloads"])
                            if rand_item.get("url"):
                                st.link_button(t["view_on_google"], rand_item["url"])

        # Export & Downloads
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
                data=generate_csv(items, st.session_state.lang).encode("utf-8-sig"),
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
                data=generate_markdown(items, lang=st.session_state.lang),
                file_name="collection_watchlist.md",
                mime="text/markdown",
                use_container_width=True,
            )

        # Previews
        st.markdown("---")
        st.subheader(t["preview_header"])

        col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
        with col_f1:
            type_opts = [t["all_types"], t["movie"], t["tv"]]
            filter_val = st.selectbox(t["filter_type"], options=type_opts, index=0)
        with col_f2:
            all_extracted_genres = set()
            for it in items:
                for g in it.get("genres", []):
                    if g:
                        all_extracted_genres.add(g)
                if it.get("primary_genre"):
                    all_extracted_genres.add(it["primary_genre"])
            genre_list = sorted(list(all_extracted_genres))
            genre_display_opts = [t["all_genres"]] + [
                f"{GENRE_ICONS.get(g, '🎬')} {GENRE_ARABIC.get(g, g) if st.session_state.lang == 'ar' else g}"
                for g in genre_list
            ]
            genre_map = {
                f"{GENRE_ICONS.get(g, '🎬')} {GENRE_ARABIC.get(g, g) if st.session_state.lang == 'ar' else g}": g
                for g in genre_list
            }
            selected_genre_display = st.selectbox(t["filter_genre"], options=genre_display_opts, index=0)
        with col_f3:
            search_query = st.text_input(t["search_box"], value="", placeholder="e.g. Inception, Breaking Bad...")

        filtered_items = items
        if filter_val == t["movie"]:
            filtered_items = [x for x in filtered_items if x.get("type") != "tv"]
        elif filter_val == t["tv"]:
            filtered_items = [x for x in filtered_items if x.get("type") == "tv"]

        if selected_genre_display != t["all_genres"]:
            chosen_genre = genre_map.get(selected_genre_display)
            if chosen_genre:
                filtered_items = [
                    x for x in filtered_items
                    if chosen_genre in x.get("genres", []) or x.get("primary_genre") == chosen_genre
                ]

        if search_query.strip():
            q = search_query.strip().lower()
            filtered_items = [x for x in filtered_items if q in x.get("title", "").lower()]

        tab_cards, tab_table, tab_md = st.tabs([t["tab_cards"], t["tab_table"], t["tab_md"]])

        with tab_cards:
            if not filtered_items:
                st.info("No matching items found.")
            else:
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
                                p_genre = it.get("primary_genre") or (it.get("genres", [None])[0] if it.get("genres") else None)
                                genre_badge = f" • {GENRE_ICONS.get(p_genre, '')} {GENRE_ARABIC.get(p_genre, p_genre) if st.session_state.lang == 'ar' else p_genre}" if p_genre else ""
                                st.caption(f"`{badge_text}`{genre_badge} {rating_str}")

                                syn_text = get_synopsis_text(it, st.session_state.lang)
                                if syn_text:
                                    short_syn = syn_text[:120] + ("..." if len(syn_text) > 120 else "")
                                    st.markdown(f"<small>{short_syn}</small>", unsafe_allow_html=True)

                                it_torrents = it.get("torrents", [])
                                badges_html = render_download_badges(it_torrents, it.get("url"))
                                if badges_html:
                                    st.markdown(badges_html, unsafe_allow_html=True)

        with tab_table:
            table_rows = []
            for it in filtered_items:
                it_torrents = it.get("torrents", [])
                has_magnet = bool(it_torrents and it_torrents[0].get("magnet"))
                syn_text = get_synopsis_text(it, st.session_state.lang)
                p_genre = it.get("primary_genre") or (it.get("genres", ["-"])[0] if it.get("genres") else "-")
                genre_str = f"{GENRE_ICONS.get(p_genre, '')} {GENRE_ARABIC.get(p_genre, p_genre) if st.session_state.lang == 'ar' else p_genre}" if p_genre != "-" else "-"
                table_rows.append({
                    "Title": it.get("title", ""),
                    "Type": it.get("type") or "-",
                    "Genre": genre_str,
                    "Year": it.get("year") or "-",
                    "Rating": f"⭐ {it['rating']}" if it.get("rating") else "-",
                    "Synopsis": (syn_text[:90] + "...") if syn_text else "-",
                    "Downloads": f"🧲 {len(it_torrents)} links" if has_magnet else ("📥 Available" if it_torrents else "-"),
                    "Link": it.get("url") or "-",
                })
            st.dataframe(table_rows, use_container_width=True)

        with tab_md:
            st.markdown(generate_markdown(filtered_items, lang=st.session_state.lang))


# ==============================================================================
# MODE 2: DIRECT MOVIE & SERIES DATABASE SEARCH
# ==============================================================================
elif st.session_state.app_mode == "search":
    st.markdown("---")
    st.subheader(t["direct_search_title"])
    st.caption(t["direct_search_desc"])

    col_s_input, col_s_btn = st.columns([4, 1])
    with col_s_input:
        direct_query = st.text_input(
            t["direct_input_label"],
            value="",
            placeholder=t["direct_input_placeholder"],
        )
    with col_s_btn:
        st.write("")
        st.write("")
        do_search = st.button(t["btn_direct_search"], type="primary", use_container_width=True)

    if do_search and direct_query.strip():
        with st.spinner(t["direct_status_searching"]):
            search_res = search_media_database(direct_query.strip(), tmdb_key=tmdb_api_key)
            st.session_state.direct_search_results = search_res

    if st.session_state.direct_search_results is not None:
        results = st.session_state.direct_search_results

        if not results:
            st.warning(t["direct_no_results"])
        else:
            st.markdown(t["direct_results_count"].format(count=len(results)))

            # Export row for search results
            st.subheader(t["export_header"])
            sd1, sd2, sd3, sd4, sd5 = st.columns(5)
            with sd1:
                st.download_button(
                    label=t["btn_txt"],
                    data=generate_txt(results),
                    file_name="search_results.txt",
                    mime="text/plain",
                    use_container_width=True,
                )
            with sd2:
                st.download_button(
                    label=t["btn_json"],
                    data=generate_json(results),
                    file_name="search_results.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with sd3:
                st.download_button(
                    label=t["btn_csv"],
                    data=generate_csv(results, st.session_state.lang).encode("utf-8-sig"),
                    file_name="search_results.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with sd4:
                st.download_button(
                    label=t["btn_letterboxd"],
                    data=generate_letterboxd_csv(results).encode("utf-8-sig"),
                    file_name="search_results_letterboxd.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with sd5:
                st.download_button(
                    label=t["btn_md"],
                    data=generate_markdown(results, collection_title="Search Results", lang=st.session_state.lang),
                    file_name="search_results.md",
                    mime="text/markdown",
                    use_container_width=True,
                )

            # Display Search Results in 3-column cards
            st.markdown("---")
            num_cols = 3
            for i in range(0, len(results), num_cols):
                chunk = results[i : i + num_cols]
                cols = st.columns(num_cols)
                for col_idx, item in enumerate(chunk):
                    with cols[col_idx]:
                        with st.container(border=True):
                            if item.get("poster_url"):
                                st.image(item["poster_url"], use_container_width=True)
                            else:
                                st.markdown(
                                    "<div style='background:#1f2937; height:220px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:40px;'>🎬</div>",
                                    unsafe_allow_html=True,
                                )

                            title_str = item.get("title", "")
                            year_str = f" ({item['year']})" if item.get("year") else ""
                            rating_str = f"⭐ {item['rating']}" if item.get("rating") else ""
                            st.markdown(f"### {title_str} {year_str}")

                            c_type = item.get("type")
                            badge_text = t.get(c_type, c_type.upper() if c_type else "")
                            p_genre = item.get("primary_genre") or (item.get("genres", [None])[0] if item.get("genres") else None)
                            genre_badge = f" • {GENRE_ICONS.get(p_genre, '')} {GENRE_ARABIC.get(p_genre, p_genre) if st.session_state.lang == 'ar' else p_genre}" if p_genre else ""
                            st.caption(f"`{badge_text}`{genre_badge} {rating_str}")

                            syn_text = get_synopsis_text(item, st.session_state.lang)
                            if syn_text:
                                st.markdown(f"<p style='font-size:13px; line-height:1.4;'>{syn_text}</p>", unsafe_allow_html=True)

                            it_torrents = item.get("torrents", [])
                            if it_torrents:
                                st.markdown(f"**{t['download_links']}**")
                                badges_html = render_download_badges(it_torrents, item.get("url"))
                                st.markdown(badges_html, unsafe_allow_html=True)
                            else:
                                st.caption(t["no_downloads"])
                                if item.get("url"):
                                    st.link_button(t["view_on_google"], item["url"])


# ==============================================================================
# MODE 3: YOUTUBE MEDIA DOWNLOADER (SINGLE VIDEO & PLAYLIST)
# ==============================================================================
elif st.session_state.app_mode == "youtube":
    st.markdown("---")
    st.subheader(t["yt_title"])
    st.caption(t["yt_subtitle"])

    col_yt_input, col_yt_btn = st.columns([4, 1])
    with col_yt_input:
        yt_url_input = st.text_input(
            t["yt_url_label"],
            value="",
            placeholder=t["yt_url_placeholder"],
            key="yt_url_field",
        )
    with col_yt_btn:
        st.write("")
        st.write("")
        btn_yt_inspect = st.button(t["yt_btn_inspect"], type="primary", use_container_width=True)

    if btn_yt_inspect and yt_url_input.strip():
        url_clean = yt_url_input.strip()
        with st.spinner(t["yt_fetching_info"]):
            try:
                info = extract_media_info(url_clean)
                st.session_state.yt_info = info
                st.session_state.yt_downloaded_data = None
                st.session_state.yt_download_filename = None
            except Exception as e:
                st.error(t["yt_error_fetching"].format(err=str(e)))
                st.session_state.yt_info = None

    if st.session_state.get("yt_info"):
        yt_data = st.session_state.yt_info
        is_pl = yt_data.get("is_playlist", False)

        st.markdown("---")
        with st.container(border=True):
            col_thumb, col_meta = st.columns([1, 2])
            with col_thumb:
                if yt_data.get("thumbnail"):
                    st.image(yt_data["thumbnail"], use_container_width=True)
                else:
                    st.markdown(
                        "<div style='background:#1f2937; height:200px; border-radius:6px; display:flex; align-items:center; justify-content:center; font-size:40px;'>📺</div>",
                        unsafe_allow_html=True,
                    )
            with col_meta:
                st.markdown(f"### {yt_data.get('title')}")
                st.markdown(f"👤 **{t['yt_uploader']}** `{yt_data.get('uploader')}`")

                if is_pl:
                    count_badge = t["yt_playlist_badge"].format(count=yt_data.get("video_count", 0))
                    st.markdown(f"📂 **{t['type_label']}:** `{count_badge}`")
                else:
                    dur_str = format_duration(yt_data.get("duration"))
                    st.markdown(f"⏱️ **{t['yt_duration']}** `{dur_str}`")
                    if yt_data.get("view_count"):
                        st.markdown(f"👁️ **{t['yt_views']}** `{yt_data.get('view_count'):,}`")

        # If playlist, allow selecting tracks
        selected_indices = None
        if is_pl:
            entries = yt_data.get("entries", [])
            with st.expander(t["yt_playlist_items"], expanded=True):
                col_sel_all, _ = st.columns([2, 3])
                with col_sel_all:
                    select_all = st.checkbox(t["yt_select_all"], value=True, key="yt_select_all_cb")

                track_options = {
                    f"{e['index']}. {e['title']} ({format_duration(e.get('duration'))})": e["index"]
                    for e in entries
                }
                default_tracks = list(track_options.keys()) if select_all else []
                chosen_tracks = st.multiselect(
                    t["yt_playlist_items"],
                    options=list(track_options.keys()),
                    default=default_tracks,
                    key="yt_chosen_tracks",
                )
                selected_indices = [track_options[k] for k in chosen_tracks]

        # Download Settings
        st.markdown("---")
        st.subheader(t["yt_download_options"])

        col_opt1, col_opt2, col_opt3 = st.columns(3)
        with col_opt1:
            media_type_choice = st.radio(
                t["yt_media_type"],
                options=[t["yt_type_audio"], t["yt_type_video"]],
                index=0,
                horizontal=True,
            )
            is_audio = (media_type_choice == t["yt_type_audio"])

        with col_opt2:
            if is_audio:
                audio_fmt = st.selectbox(t["yt_audio_format"], options=["MP3", "M4A", "WAV"], index=0)
            else:
                video_fmt = st.selectbox("Video Format:", options=["MP4"], index=0)

        with col_opt3:
            if is_audio:
                audio_qual = st.selectbox(
                    t["yt_audio_quality"],
                    options=["320 kbps (High Quality)", "192 kbps (Standard)", "128 kbps (Compact)"],
                    index=0,
                )
                bitrate_val = audio_qual.split()[0]
            else:
                video_qual = st.selectbox(
                    t["yt_video_quality"],
                    options=["1080p (Full HD)", "720p (HD)", "480p (SD)", "360p", "Best Available"],
                    index=1,
                )
                if "1080" in video_qual:
                    res_val = "1080p"
                elif "720" in video_qual:
                    res_val = "720p"
                elif "480" in video_qual:
                    res_val = "480p"
                elif "360" in video_qual:
                    res_val = "360p"
                else:
                    res_val = "best"

        st.write("")
        btn_start_dl = st.button(t["yt_btn_start_download"], type="primary", use_container_width=True)

        if btn_start_dl:
            if is_pl and not selected_indices:
                st.warning("Please select at least one track to download.")
            else:
                download_dir = Path("temp_downloads")
                download_dir.mkdir(exist_ok=True)

                status_placeholder = st.empty()
                progress_bar = st.progress(0.0)

                def ui_progress_hook(d: Dict[str, Any]):
                    if d.get("status") == "downloading":
                        total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                        downloaded = d.get("downloaded_bytes", 0)
                        speed = d.get("speed")
                        speed_str = f" • {format_file_size(speed)}/s" if speed else ""
                        eta = d.get("eta")
                        eta_str = f" • ETA: {eta}s" if eta else ""
                        if total_bytes > 0:
                            ratio = min(1.0, max(0.0, downloaded / total_bytes))
                            progress_bar.progress(ratio)
                            status_placeholder.text(f"⏳ {int(ratio*100)}% ({format_file_size(downloaded)} / {format_file_size(total_bytes)}){speed_str}{eta_str}")
                    elif d.get("status") == "finished":
                        progress_bar.progress(1.0)
                        status_placeholder.text("⚙️ Processing media with FFmpeg...")

                with st.spinner(t["yt_downloading"]):
                    try:
                        if is_pl:
                            def on_item(cur: int, tot: int, title: str):
                                status_placeholder.text(t["yt_downloading_item"].format(cur=cur, tot=tot, title=title[:40]))
                                progress_bar.progress(min(1.0, cur / tot))

                            zip_file, files = download_playlist_media(
                                playlist_url=yt_url_input.strip(),
                                output_dir=download_dir,
                                media_type="audio" if is_audio else "video",
                                media_format=audio_fmt.lower() if is_audio else "mp4",
                                quality=bitrate_val if is_audio else res_val,
                                selected_indices=selected_indices,
                                item_callback=on_item,
                                progress_hook=ui_progress_hook,
                            )
                            with open(zip_file, "rb") as f:
                                st.session_state.yt_downloaded_data = f.read()
                            st.session_state.yt_download_filename = zip_file.name
                            st.session_state.yt_is_zip = True
                        else:
                            out_file = download_single_video(
                                url=yt_url_input.strip(),
                                output_dir=download_dir,
                                media_type="audio" if is_audio else "video",
                                media_format=audio_fmt.lower() if is_audio else "mp4",
                                quality=bitrate_val if is_audio else res_val,
                                progress_hook=ui_progress_hook,
                            )
                            with open(out_file, "rb") as f:
                                st.session_state.yt_downloaded_data = f.read()
                            st.session_state.yt_download_filename = out_file.name
                            st.session_state.yt_is_zip = False

                        status_placeholder.empty()
                        progress_bar.empty()
                        st.success(t["yt_download_complete"])
                    except Exception as err:
                        st.error(f"Download Error: {err}")
                        st.session_state.yt_downloaded_data = None

        if st.session_state.get("yt_downloaded_data") is not None:
            data_bytes = st.session_state.yt_downloaded_data
            fname = st.session_state.yt_download_filename
            is_zip_dl = st.session_state.get("yt_is_zip", False)
            btn_lbl = t["yt_btn_save_zip"] if is_zip_dl else t["yt_btn_save_file"]
            mime_type = "application/zip" if is_zip_dl else ("audio/mpeg" if fname.endswith(".mp3") else ("audio/wav" if fname.endswith(".wav") else "video/mp4"))

            col_dl_btn, col_dl_info = st.columns([2, 2])
            with col_dl_btn:
                st.download_button(
                    label=f"{btn_lbl} ({format_file_size(len(data_bytes))})",
                    data=data_bytes,
                    file_name=fname,
                    mime=mime_type,
                    type="primary",
                    use_container_width=True,
                )
            with col_dl_info:
                st.info(f"📄 **{fname}** ({format_file_size(len(data_bytes))})")

