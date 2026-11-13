"""Media enrichment module for Google Collection Extractor (CineHarvest).

Fetches:
1. Movie torrent download links & magnet links via YTS API (with automatic mirror fallback).
2. TV series torrents via EZTV API (when IMDb ID is found).
3. Concise plot summaries, posters, and types via Wikipedia REST API & IMDb suggestions.
4. Optional Arabic search & Arabic plot synopses via Arabic Wikipedia.
"""

import concurrent.futures
import difflib
import logging
import re
import threading
import urllib.parse
from typing import Dict, Any, List, Optional, Callable, Tuple

import requests
from cleaner import extract_title_and_year

logger = logging.getLogger("google_collection_extractor")

TRACKERS = [
    "udp://open.demonii.com:1337/announce",
    "udp://tracker.openbittorrent.com:80",
    "udp://tracker.coppersurfer.tk:6969",
    "udp://glotorrents.pw:6969/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://torrent.gresille.org:80/announce",
    "udp://p4p.arenabg.com:1337",
    "udp://tracker.leechers-paradise.org:6969",
]
TRACKER_PARAM = "".join(f"&tr={urllib.parse.quote(tr)}" for tr in TRACKERS)

YTS_API_MIRRORS = [
    "https://yts.lt/api/v2/list_movies.json",
    "https://yts.bz/api/v2/list_movies.json",
    "https://yts.gg/api/v2/list_movies.json",
    "https://movies-api.accel.li/api/v2/list_movies.json",
]
EZTV_API_URL = "https://eztvx.to/api/get-torrents"
WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKI_AR_SUMMARY_URL = "https://ar.wikipedia.org/api/rest_v1/page/summary"
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKI_AR_SEARCH_URL = "https://ar.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "CineHarvest/2.1 (OpenSource; contact: github.com/evile92/cineharvest)"}

_thread_local = threading.local()
_yts_mirror_lock = threading.Lock()
_preferred_yts_idx = 0


def _get_session() -> requests.Session:
    """Return a thread-local requests.Session for HTTP keep-alive connection pooling."""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update(HEADERS)
        _thread_local.session = sess
    return sess


TV_TYPE_PATTERNS = re.compile(
    r"\b("
    r"television series|tv series|tv show|television show|"
    r"miniseries|mini-series|television miniseries|tv miniseries|"
    r"sitcom|comedy series|drama series|crime drama series|"
    r"animated series|anime series|docuseries|documentary series|"
    r"television program|tv program|serial drama|soap opera|telenovela|"
    r"web series|limited series|anthology series|"
    r"مسلسل|سلسلة تلفزيونية|برنامج تلفزيوني|مسلسل قصير"
    r")\b",
    re.I,
)

MOVIE_TYPE_PATTERNS = re.compile(
    r"\b("
    r"feature film|short film|television film|tv film|tv movie|television movie|"
    r"direct-to-video film|animated film|documentary film|concert film|"
    r"comedy film|drama film|action film|horror film|thriller film|science fiction film|"
    r"film directed by|directed by|film starring|film written|film produced|"
    r"film released|american film|british film|french film|film|movie|motion picture|"
    r"فلم|فيلم|شريط سينمائي"
    r")\b",
    re.I,
)

NUM_MAP = {
    "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
    "12": "twelve", "28": "twenty-eight",
}

GENRE_KEYWORDS = [
    ("Action", re.compile(r"\b(action)\b", re.I)),
    ("Adventure", re.compile(r"\b(adventure)\b", re.I)),
    ("Animation", re.compile(r"\b(animation|animated|anime)\b", re.I)),
    ("Biography", re.compile(r"\b(biography|biographical|biopic)\b", re.I)),
    ("Comedy", re.compile(r"\b(comedy|comic|sitcom)\b", re.I)),
    ("Crime", re.compile(r"\b(crime|gangster|police|mafia)\b", re.I)),
    ("Documentary", re.compile(r"\b(documentary|docuseries)\b", re.I)),
    ("Drama", re.compile(r"\b(drama|dramatic)\b", re.I)),
    ("Fantasy", re.compile(r"\b(fantasy)\b", re.I)),
    ("History", re.compile(r"\b(historical|history)\b", re.I)),
    ("Horror", re.compile(r"\b(horror|slasher|supernatural|zombie)\b", re.I)),
    ("Mystery", re.compile(r"\b(mystery|detective)\b", re.I)),
    ("Romance", re.compile(r"\b(romance|romantic)\b", re.I)),
    ("Sci-Fi", re.compile(r"\b(sci-fi|science fiction|space opera|cyberpunk)\b", re.I)),
    ("Thriller", re.compile(r"\b(thriller|suspense|psychological thriller)\b", re.I)),
    ("War", re.compile(r"\b(war|military|battle)\b", re.I)),
    ("Western", re.compile(r"\b(western)\b", re.I)),
]

ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF]")
LEADING_YEAR_IN_DESC_RE = re.compile(r"^((?:19|20)\d{2})\b")
STOPWORDS = {"the", "a", "an", "of", "and"}


def detect_genres_from_text(text: str) -> List[str]:
    """Detect movie/series genres from description or synopsis text."""
    if not text:
        return []
    found = []
    for g_name, pattern in GENRE_KEYWORDS:
        if pattern.search(text):
            found.append(g_name)
    return found


def build_magnet_uri(hash_str: str, title: str, quality: str = "") -> str:
    """Construct a high-availability magnet URI with standard trackers."""
    display_name = f"{title} [{quality}]".strip() if quality else title
    encoded_name = urllib.parse.quote(display_name)
    return f"magnet:?xt=urn:btih:{hash_str}&dn={encoded_name}{TRACKER_PARAM}"


def _build_yts_torrents(movie_obj: Dict[str, Any], fallback_title: str) -> List[Dict[str, Any]]:
    """Build normalized torrent dictionary list from a YTS movie payload."""
    torrents_list = []
    m_title = movie_obj.get("title") or fallback_title
    for t in movie_obj.get("torrents", []):
        q = t.get("quality", "")
        t_hash = t.get("hash", "")
        magnet = build_magnet_uri(t_hash, m_title, q) if t_hash else None
        torrents_list.append({
            "quality": q,
            "type": t.get("type", "WEB"),
            "size": t.get("size", ""),
            "url": t.get("url", ""),
            "magnet": magnet,
        })
    return torrents_list


def _query_yts(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Query YTS API across configured mirrors with automatic fallback."""
    global _preferred_yts_idx
    if not query:
        return []

    sess = _get_session()
    with _yts_mirror_lock:
        start_idx = _preferred_yts_idx

    ordered_indices = [
        (start_idx + offset) % len(YTS_API_MIRRORS)
        for offset in range(len(YTS_API_MIRRORS))
    ]

    for idx in ordered_indices:
        mirror = YTS_API_MIRRORS[idx]
        try:
            resp = sess.get(mirror, params={"query_term": query, "limit": limit}, timeout=6)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if idx != start_idx:
                with _yts_mirror_lock:
                    _preferred_yts_idx = idx
            return data.get("data", {}).get("movies") or []
        except Exception:
            continue
    return []


def fetch_yts_movie_data(title: str, expected_year: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Search YTS API for a movie and extract synopsis, ratings, and download links."""
    base_title, parsed_year = extract_title_and_year(title)
    target_year = expected_year or parsed_year

    clean_query = re.sub(r"[^\w\s]", " ", base_title).strip()
    movies = _query_yts(clean_query)

    if not movies:
        tokens = clean_query.split()
        if tokens and tokens[0] in NUM_MAP:
            alt_query = NUM_MAP[tokens[0]] + " " + " ".join(tokens[1:])
            movies = _query_yts(alt_query)

    if not movies:
        return None

    target_lower = base_title.lower()
    best_movie = None
    best_score = -1.0

    for m in movies:
        m_title = (m.get("title") or "").lower()
        score = difflib.SequenceMatcher(None, target_lower, m_title).ratio()
        m_year = str(m.get("year") or "")
        if target_year and m_year:
            if m_year == target_year:
                score += 0.15
            elif m_year.isdigit() and target_year.isdigit() and abs(int(m_year) - int(target_year)) > 1:
                score -= 0.10

        if score > best_score:
            best_score = score
            best_movie = m

    if best_score < 0.62 or not best_movie:
        return None

    torrents_list = _build_yts_torrents(best_movie, base_title)
    summary = best_movie.get("summary") or best_movie.get("synopsis") or best_movie.get("description_full")
    if summary:
        summary = summary.replace("\n", " ").strip()

    return {
        "year": str(best_movie.get("year", "")) if best_movie.get("year") else None,
        "rating": best_movie.get("rating"),
        "poster_url": best_movie.get("large_cover_image") or best_movie.get("medium_cover_image"),
        "synopsis": summary,
        "genres": best_movie.get("genres", []),
        "torrents": torrents_list,
        "imdb_code": best_movie.get("imdb_code"),
        "source": "yts",
    }


def _format_bytes(size_val: Any) -> str:
    """Convert numeric byte size to human-readable MB/GB."""
    try:
        b = int(size_val)
        if b <= 0:
            return ""
        if b >= 1024 * 1024 * 1024:
            return f"{b / (1024 ** 3):.2f} GB"
        return f"{b / (1024 ** 2):.0f} MB"
    except Exception:
        return str(size_val) if size_val else ""


def fetch_imdb_metadata(
    title: str,
    expected_type: Optional[str] = None,
    expected_year: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Query IMDb's public suggestion endpoint for IMDb ID, release year, high-res poster, and type."""
    base_title, parsed_year = extract_title_and_year(title)
    target_year = expected_year or parsed_year

    clean = re.sub(r"[^\w\s]", " ", base_title).strip().lower()
    if not clean:
        return None

    first_char = clean[0] if (clean[0].isascii() and clean[0].isalnum()) else "x"
    url = f"https://v3.sg.media-imdb.com/suggestion/{first_char}/{urllib.parse.quote(clean)}.json"
    try:
        resp = _get_session().get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = [d for d in data.get("d", []) if str(d.get("id", "")).startswith("tt")]
        if not items:
            return None

        best_item = None
        best_score = -1.0
        target_lower = base_title.strip().lower()

        for d in items:
            cand_title = str(d.get("l", "")).strip().lower()
            qid = str(d.get("qid", "")).lower()
            cand_type = (
                "tv"
                if ("series" in qid or "tvmini" in qid or "tvshow" in qid)
                else ("movie" if ("movie" in qid or "film" in qid) else None)
            )
            cand_year = str(d["y"]) if d.get("y") else None

            score = difflib.SequenceMatcher(None, target_lower, cand_title).ratio()
            if expected_type and cand_type == expected_type:
                score += 0.15
            if target_year and cand_year:
                if cand_year == target_year:
                    score += 0.18
                elif cand_year.isdigit() and target_year.isdigit() and abs(int(cand_year) - int(target_year)) > 1:
                    score -= 0.10

            if score > best_score:
                best_score = score
                best_item = (d, cand_type)

        if not best_item or best_score < 0.62:
            return None

        d, detected_type = best_item
        poster = d.get("i", {}).get("imageUrl") if isinstance(d.get("i"), dict) else None
        return {
            "imdb_code": d.get("id"),
            "year": str(d["y"]) if d.get("y") else None,
            "poster_url": poster,
            "type": detected_type,
        }
    except Exception:
        return None


def fetch_eztv_torrents(imdb_id: str, series_title: str = "") -> List[Dict[str, Any]]:
    """Fetch TV series torrents from EZTV API using clean numeric IMDb ID and verify title match."""
    clean_id = re.sub(r"[^\d]", "", imdb_id)
    if not clean_id:
        return []

    try:
        resp = _get_session().get(EZTV_API_URL, params={"imdb_id": clean_id, "limit": 10}, timeout=7)
        if resp.status_code != 200:
            return []
        data = resp.json()
        torrents = data.get("torrents", [])
        results = []

        # Build meaningful word tokens (drop leading stopword like 'the' if multiple words)
        raw_tokens = re.findall(r"[a-z0-9]+", series_title.lower()) if series_title else []
        sig_tokens = [w for w in raw_tokens if w not in STOPWORDS] or raw_tokens
        check_tokens = sig_tokens[:2]

        for t in torrents:
            t_title = t.get("title", "")
            if check_tokens:
                t_words = set(re.findall(r"[a-z0-9]+", t_title.lower()))
                if not all(tok in t_words for tok in check_tokens):
                    continue

            res_match = re.search(r"\b(2160p|1080p|720p|480p)\b", t_title, re.I)
            res_str = res_match.group(1) if res_match else "HD"
            ep_match = re.search(r"\b(S\d{1,2}E\d{1,2}|S\d{1,2})\b", t_title, re.I)
            ep_str = f"{ep_match.group(1).upper()} " if ep_match else ""

            results.append({
                "title": t_title,
                "quality": f"{ep_str}{res_str}".strip(),
                "season": t.get("season"),
                "episode": t.get("episode"),
                "size": _format_bytes(t.get("size_bytes")),
                "url": t.get("torrent_url"),
                "magnet": t.get("magnet_url"),
            })
        return results
    except Exception:
        return []


def _classify_wiki_text(desc: str, lead: str) -> Optional[str]:
    """Determine 'tv' or 'movie' from Wikipedia short description and lead sentence."""
    if desc:
        if TV_TYPE_PATTERNS.search(desc):
            return "tv"
        if MOVIE_TYPE_PATTERNS.search(desc):
            return "movie"

    if lead:
        # Restrict scan to opening sentence/clause (~220 chars) to avoid remake references later
        snippet = lead[:220]
        if TV_TYPE_PATTERNS.search(snippet) and not MOVIE_TYPE_PATTERNS.search(snippet):
            return "tv"
        if MOVIE_TYPE_PATTERNS.search(snippet):
            return "movie"

    return None


def _inspect_wiki_page(
    candidate: str, base_summary_url: str = WIKI_SUMMARY_URL
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Query a Wikipedia REST summary endpoint and return (extract, image, media_type, page_title)."""
    encoded = urllib.parse.quote(candidate.replace(" ", "_"))
    url = f"{base_summary_url}/{encoded}"
    try:
        resp = _get_session().get(url, timeout=5)
        if resp.status_code != 200:
            return None, None, None, None
        data = resp.json()
        if data.get("type") == "disambiguation":
            return None, None, None, None

        extract = data.get("extract")
        desc = data.get("description", "")
        canonical_title = data.get("title") or candidate
        image_url = (
            data.get("thumbnail", {}).get("source")
            or data.get("originalimage", {}).get("source")
        )
        cleaned = None
        if extract and len(extract.strip()) > 20:
            cleaned = re.sub(r"\s+", " ", extract).strip()

        if "refer to:" in (cleaned or "") or "may refer to:" in (cleaned or "") or "قد يشير" in (cleaned or ""):
            return None, None, None, None

        detected_type = _classify_wiki_text(f"{candidate} {desc}".strip(), cleaned or "")
        return cleaned, image_url, detected_type, canonical_title
    except Exception:
        return None, None, None, None


def search_wikipedia_media_title(
    title: str, expected_type: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Search Wikipedia for title to find TV series or Film pages."""
    try:
        resp = _get_session().get(
            WIKI_SEARCH_URL,
            params={"action": "query", "list": "search", "format": "json", "srsearch": title, "srlimit": 6},
            timeout=4,
        )
        if resp.status_code != 200:
            return None, None
        results = resp.json().get("query", {}).get("search", [])
        target_lower = title.lower()
        for r in results:
            t = r.get("title", "")
            clean_t = re.sub(r"\s*\([^)]*\)", "", t).strip().lower()
            if clean_t == target_lower or t.lower().startswith(target_lower + " ("):
                is_tv = bool(re.search(r"\b(tv series|television series|miniseries|mini-series)\b", t, re.I))
                is_movie = bool(re.search(r"\b(film|movie)\b", t, re.I))
                if expected_type == "tv" and is_tv:
                    return t, "tv"
                if expected_type == "movie" and is_movie:
                    return t, "movie"
                if is_tv:
                    return t, "tv"
                if is_movie:
                    return t, "movie"
    except Exception:
        pass
    return None, None


def fetch_wikipedia_details_full(
    title: str,
    media_type: Optional[str] = None,
    year: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Fetch (summary, poster_url, detected_type, resolved_wiki_title) from English Wikipedia."""
    base_title, parsed_year = extract_title_and_year(title)
    target_year = year or parsed_year

    if media_type == "tv":
        candidates = []
        if target_year:
            candidates.append(f"{base_title} ({target_year} TV series)")
        candidates.extend([f"{base_title} (TV series)", f"{base_title} (miniseries)", base_title])
        for cand in candidates:
            s, p, dt, canon = _inspect_wiki_page(cand)
            if (s or p) and (dt == "tv" or cand != base_title):
                return s, p, dt or "tv", canon
        hit_title, _ = search_wikipedia_media_title(base_title, expected_type="tv")
        if hit_title:
            s, p, dt, canon = _inspect_wiki_page(hit_title)
            if s or p:
                return s, p, dt or "tv", canon
        return None, None, "tv", None

    if media_type == "movie":
        candidates = []
        if target_year:
            candidates.append(f"{base_title} ({target_year} film)")
        candidates.extend([f"{base_title} (film)", base_title, f"{base_title} (movie)"])
        for cand in candidates:
            s, p, dt, canon = _inspect_wiki_page(cand)
            if (s or p) and (dt != "tv"):
                return s, p, dt or "movie", canon
        return None, None, "movie", None

    # Unknown media_type: check direct title first
    summary, poster, detected_type, canon_direct = _inspect_wiki_page(base_title)
    if detected_type:
        return summary, poster, detected_type, canon_direct

    movie_cands = [f"{base_title} ({target_year} film)"] if target_year else []
    movie_cands.extend([f"{base_title} (film)", f"{base_title} (movie)"])
    for cand in movie_cands:
        s, p, dt, canon = _inspect_wiki_page(cand)
        if dt == "movie" or (s and MOVIE_TYPE_PATTERNS.search(s[:220])):
            return s, p, "movie", canon

    tv_cands = [f"{base_title} ({target_year} TV series)"] if target_year else []
    tv_cands.extend([f"{base_title} (TV series)", f"{base_title} (miniseries)"])
    for cand in tv_cands:
        s, p, dt, canon = _inspect_wiki_page(cand)
        if dt == "tv" or (s and TV_TYPE_PATTERNS.search(s[:220])):
            return s, p, "tv", canon

    hit_title, hit_type = search_wikipedia_media_title(base_title)
    if hit_title:
        s, p, dt, canon = _inspect_wiki_page(hit_title)
        if s or p:
            return s, p, dt or hit_type, canon

    if summary or poster:
        return summary, poster, detected_type, canon_direct

    return None, None, None, None


def fetch_wikipedia_details(
    title: str, media_type: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch (overview, poster_url, media_type) from Wikipedia (backwards-compatible wrapper)."""
    summary, poster, detected_type, _ = fetch_wikipedia_details_full(title, media_type=media_type)
    return summary, poster, detected_type


def fetch_wikipedia_summary(title: str, media_type: Optional[str] = None) -> Optional[str]:
    """Fetch a concise 2-3 sentence overview from Wikipedia's free REST API."""
    summary, _, _ = fetch_wikipedia_details(title, media_type)
    return summary


def fetch_arabic_wikipedia_summary(
    title: str,
    media_type: Optional[str] = None,
    wiki_title: Optional[str] = None,
) -> Optional[str]:
    """Fetch native Arabic plot synopsis from Arabic Wikipedia via interlanguage link or direct lookup."""
    sess = _get_session()
    base_title, _ = extract_title_and_year(title)

    # Prioritize exact matched English Wikipedia title (resolves in 1 langlink lookup)
    candidates: List[str] = []
    if wiki_title:
        candidates.append(wiki_title)

    if media_type == "tv":
        extra = [f"{base_title} (TV series)", base_title]
    elif media_type == "movie":
        extra = [f"{base_title} (film)", base_title]
    else:
        extra = [f"{base_title} (film)", f"{base_title} (TV series)", base_title]

    for c in extra:
        if c not in candidates:
            candidates.append(c)

    # Method 1: English -> Arabic interlanguage link resolution
    for cand in candidates:
        try:
            resp = sess.get(
                WIKI_SEARCH_URL,
                params={
                    "action": "query",
                    "prop": "langlinks",
                    "lllang": "ar",
                    "titles": cand,
                    "redirects": "1",
                    "format": "json",
                },
                timeout=4,
            )
            if resp.status_code != 200:
                continue
            pages = resp.json().get("query", {}).get("pages", {})
            for p_val in pages.values():
                ll = p_val.get("langlinks", [])
                if ll and ll[0].get("*"):
                    ar_title = ll[0]["*"]
                    ar_extract, _, _, _ = _inspect_wiki_page(ar_title, base_summary_url=WIKI_AR_SUMMARY_URL)
                    if ar_extract:
                        return ar_extract
        except Exception:
            continue

    # Method 2: Direct lookup on Arabic Wikipedia
    for cand in [base_title, f"{base_title} (فيلم)", f"{base_title} (مسلسل)"]:
        ar_extract, _, _, _ = _inspect_wiki_page(cand, base_summary_url=WIKI_AR_SUMMARY_URL)
        if ar_extract:
            return ar_extract

    return None


def enrich_single_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single movie or series item with synopsis, year, poster, and torrent links."""
    enriched = dict(item)
    raw_title = item.get("title", "")
    clean_name, parsed_year = extract_title_and_year(raw_title)
    if parsed_year and not enriched.get("year"):
        enriched["year"] = parsed_year

    known_type = item.get("type")
    target_year = enriched.get("year")

    # 1. Fetch Wikipedia details & resolved canonical title
    wiki_summary, wiki_poster, detected_type, matched_wiki_title = fetch_wikipedia_details_full(
        clean_name, media_type=known_type, year=target_year
    )
    final_type = known_type or detected_type

    yts_data = None
    # 2. Search YTS for movie torrents, year, rating, and synopsis ONLY if not TV series
    if final_type != "tv":
        yts_data = fetch_yts_movie_data(clean_name, expected_year=target_year)
        if yts_data:
            if not final_type:
                final_type = "movie"
            if not enriched.get("year") and yts_data.get("year"):
                enriched["year"] = yts_data["year"]
            if not enriched.get("rating") and yts_data.get("rating"):
                enriched["rating"] = yts_data["rating"]
            if not enriched.get("poster_url") and yts_data.get("poster_url"):
                enriched["poster_url"] = yts_data["poster_url"]
            if yts_data.get("synopsis"):
                enriched["synopsis"] = yts_data["synopsis"]
            if yts_data.get("torrents"):
                enriched["torrents"] = yts_data["torrents"]
            if yts_data.get("imdb_code"):
                enriched["imdb_code"] = yts_data["imdb_code"]

    # 3. Resolve IMDb metadata if missing imdb_code, year, poster, or if TV series
    if final_type == "tv" or not enriched.get("imdb_code") or not enriched.get("year") or not enriched.get("poster_url"):
        imdb_meta = fetch_imdb_metadata(
            clean_name,
            expected_type=final_type,
            expected_year=enriched.get("year"),
        )
        if imdb_meta:
            if not final_type and imdb_meta.get("type"):
                final_type = imdb_meta["type"]
            if not enriched.get("imdb_code") and imdb_meta.get("imdb_code"):
                enriched["imdb_code"] = imdb_meta["imdb_code"]
            if not enriched.get("year") and imdb_meta.get("year"):
                enriched["year"] = imdb_meta["year"]
            if not enriched.get("poster_url") and imdb_meta.get("poster_url"):
                enriched["poster_url"] = imdb_meta["poster_url"]

    # 4. Check EZTV if imdb_code is available and item is a TV show
    if enriched.get("imdb_code") and final_type == "tv":
        eztv_torrents = fetch_eztv_torrents(enriched["imdb_code"], series_title=clean_name)
        if eztv_torrents:
            enriched["torrents"] = eztv_torrents

    # 5. Fill in missing synopsis or poster from Wikipedia
    if not enriched.get("synopsis") and wiki_summary:
        enriched["synopsis"] = wiki_summary
    if not enriched.get("poster_url") and wiki_poster:
        enriched["poster_url"] = wiki_poster

    if not final_type:
        final_type = "movie"
    enriched["type"] = final_type

    # 6. Fetch native Arabic plot overview using exact resolved English Wikipedia title when available
    if not enriched.get("synopsis_ar"):
        ar_summary = fetch_arabic_wikipedia_summary(
            clean_name,
            media_type=final_type,
            wiki_title=matched_wiki_title,
        )
        if ar_summary:
            enriched["synopsis_ar"] = ar_summary

    # 7. Determine Genres
    item_genres = []
    if yts_data and yts_data.get("genres"):
        item_genres = yts_data["genres"]
    elif enriched.get("synopsis"):
        item_genres = detect_genres_from_text(enriched["synopsis"])

    if not item_genres:
        item_genres = ["Drama"] if final_type == "tv" else ["Other"]

    enriched["genres"] = item_genres
    enriched["primary_genre"] = item_genres[0] if item_genres else "Other"
    enriched["_wiki_title"] = matched_wiki_title

    return enriched


def enrich_media_items(
    items: List[Dict[str, Any]],
    max_workers: int = 10,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Enrich a list of items concurrently using a thread pool and keep-alive sessions."""
    total = len(items)
    enriched_list: List[Optional[Dict[str, Any]]] = [None] * total
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(enrich_single_item, item): idx
            for idx, item in enumerate(items)
        }

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                res = future.result()
                res.pop("_wiki_title", None)
                enriched_list[idx] = res
            except Exception as e:
                logger.debug("Enrichment error on item %d: %s", idx, e)
                enriched_list[idx] = items[idx]

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return [item for item in enriched_list if item is not None]


_NON_MEDIA_WIKI_QUALIFIER_RE = re.compile(
    r"\((?:توضيح|رواية|كتاب|قصة|مسرحية|ألبوم|أغنية|لعبة(?:\s+فيديو)?|"
    r"disambiguation|novel|book|play|album|song|video game|soundtrack)\)",
    re.I,
)


def _search_wikipedia_opensearch(clean_q: str, api_url: str, summary_base: str, is_ar: bool = False) -> List[Dict[str, Any]]:
    """Search Wikipedia OpenSearch API and inspect candidate movie/TV pages concurrently."""
    found: List[Dict[str, Any]] = []
    sess = _get_session()
    wiki_titles: List[str] = []

    for attempt in range(2):
        try:
            resp = sess.get(
                api_url,
                params={"action": "opensearch", "search": clean_q, "limit": 6, "namespace": 0, "format": "json"},
                timeout=7,
            )
            if resp.status_code == 200:
                data = resp.json()
                wiki_titles = data[1] if len(data) > 1 else []
                break
            if resp.status_code not in (429, 500, 502, 503, 504):
                return found
        except Exception as e:
            if attempt == 1:
                logger.debug("Wikipedia OpenSearch error (%s): %s", "ar" if is_ar else "en", e)

    candidates = [wt for wt in wiki_titles if wt and not _NON_MEDIA_WIKI_QUALIFIER_RE.search(wt)]
    if not candidates:
        return found

    def _inspect_candidate(wt: str) -> Optional[Dict[str, Any]]:
        w_summary, w_poster, w_type, canon = _inspect_wiki_page(wt, base_summary_url=summary_base)
        if not (w_summary or w_poster) or w_type not in ("movie", "tv"):
            return None

        clean_wt = re.sub(r"\s*\([^)]*\)", "", wt).strip() or wt
        w_genres = detect_genres_from_text(w_summary) if (w_summary and not is_ar) else []
        if not w_genres:
            w_genres = ["Drama"] if w_type == "tv" else ["Other"]

        wiki_domain = "ar.wikipedia.org" if is_ar else "en.wikipedia.org"
        return {
            "title": clean_wt,
            "type": w_type,
            "genres": w_genres,
            "primary_genre": w_genres[0],
            "year": None,
            "rating": None,
            "poster_url": w_poster,
            "synopsis": None if is_ar else w_summary,
            "synopsis_ar": w_summary if is_ar else None,
            "torrents": [],
            "url": f"https://{wiki_domain}/wiki/{urllib.parse.quote(wt.replace(' ', '_'))}",
            "imdb_code": None,
            "_wiki_title": canon if not is_ar else None,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(candidates))) as executor:
        for item in executor.map(_inspect_candidate, candidates):
            if item is not None:
                found.append(item)

    return found


def search_media_database(
    query: str,
    tmdb_key: Optional[str] = None,
    lang: str = "en",
) -> List[Dict[str, Any]]:
    """Search YTS, English/Arabic Wikipedia, IMDb, EZTV, and optional TMDB concurrently."""
    clean_q = query.strip()
    if not clean_q:
        return []

    has_arabic = bool(ARABIC_CHAR_RE.search(clean_q))

    # Run YTS, English Wikipedia, and (when relevant) Arabic Wikipedia concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        fut_yts = executor.submit(_query_yts, clean_q, 12)
        fut_wiki_en = executor.submit(_search_wikipedia_opensearch, clean_q, WIKI_SEARCH_URL, WIKI_SUMMARY_URL, False)
        fut_wiki_ar = (
            executor.submit(_search_wikipedia_opensearch, clean_q, WIKI_AR_SEARCH_URL, WIKI_AR_SUMMARY_URL, True)
            if has_arabic
            else None
        )

        yts_movies = fut_yts.result()
        wiki_en_items = fut_wiki_en.result()
        wiki_ar_items = fut_wiki_ar.result() if fut_wiki_ar else []

    results: List[Dict[str, Any]] = []
    seen_titles = set()

    for m in yts_movies:
        m_title = (m.get("title") or "").strip()
        if not m_title:
            continue
        seen_titles.add((m_title.lower(), "movie"))
        summary = m.get("summary") or m.get("synopsis") or m.get("description_full") or ""
        if summary:
            summary = summary.replace("\n", " ").strip()
        m_genres = m.get("genres") or (detect_genres_from_text(summary) if summary else []) or ["Other"]

        results.append({
            "title": m_title,
            "type": "movie",
            "genres": m_genres,
            "primary_genre": m_genres[0],
            "year": str(m.get("year", "")) if m.get("year") else None,
            "rating": m.get("rating"),
            "poster_url": m.get("large_cover_image") or m.get("medium_cover_image"),
            "synopsis": summary,
            "synopsis_ar": None,
            "torrents": _build_yts_torrents(m, m_title),
            "url": m.get("url"),
            "imdb_code": m.get("imdb_code"),
        })

    ordered_wiki = (wiki_ar_items + wiki_en_items) if has_arabic else (wiki_en_items + wiki_ar_items)
    for item in ordered_wiki:
        key = (item["title"].lower(), item.get("type"))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        results.append(item)

    def enrich_result_extra(res: Dict[str, Any]):
        wiki_title = res.pop("_wiki_title", None)
        if not res.get("synopsis_ar"):
            try:
                ar_sum = fetch_arabic_wikipedia_summary(
                    res["title"],
                    media_type=res.get("type"),
                    wiki_title=wiki_title,
                )
                if ar_sum:
                    res["synopsis_ar"] = ar_sum
            except Exception:
                pass

        try:
            if res.get("type") == "tv" or not res.get("imdb_code") or not res.get("year") or not res.get("poster_url"):
                imdb_meta = fetch_imdb_metadata(
                    res["title"],
                    expected_type=res.get("type"),
                    expected_year=res.get("year"),
                )
                if imdb_meta:
                    if not res.get("imdb_code") and imdb_meta.get("imdb_code"):
                        res["imdb_code"] = imdb_meta["imdb_code"]
                    if not res.get("year") and imdb_meta.get("year"):
                        res["year"] = imdb_meta["year"]
                    if imdb_meta.get("poster_url") and (not res.get("poster_url") or "wikipedia" in str(res.get("poster_url"))):
                        res["poster_url"] = imdb_meta["poster_url"]

            if res.get("type") == "tv" and res.get("imdb_code") and not res.get("torrents"):
                eztv_list = fetch_eztv_torrents(res["imdb_code"], series_title=res["title"])
                if eztv_list:
                    res["torrents"] = eztv_list
        except Exception:
            pass

    if results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(enrich_result_extra, results))

    if tmdb_key:
        try:
            from tmdb import enrich_items_with_tmdb
            results = enrich_items_with_tmdb(results, tmdb_key, lang=lang)
        except Exception as e:
            logger.debug("TMDB search enrichment error: %s", e)

    return results
