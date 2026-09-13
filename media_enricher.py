"""Media enrichment module for Google Collection Extractor.

Fetches:
1. Movie torrent download links & magnet links via YTS API.
2. TV series torrents via EZTV API (when IMDb ID is found).
3. Concise plot summaries/synopsis via YTS API & Wikipedia REST API (100% free, no API key).
"""

import concurrent.futures
import difflib
import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional, Callable, Tuple

logger = logging.getLogger("google_collection_extractor")

# Trackers for robust magnet links
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

YTS_API_URL = "https://movies-api.accel.li/api/v2/list_movies.json"
EZTV_API_URL = "https://eztvx.to/api/get-torrents"
WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKI_AR_SUMMARY_URL = "https://ar.wikipedia.org/api/rest_v1/page/summary"
WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json"
HEADERS = {"User-Agent": "GoogleCollectionMediaExtractor/2.0 (OpenSource)"}

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
    r"film released|american film|british film|french film|film\b|movie\b|motion picture|"
    r"فيلم|شريط سينمائي"
    r")\b",
    re.I,
)

# Number-to-word translation for query fallback
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


def _query_yts(query: str) -> List[Dict[str, Any]]:
    """Helper to query YTS API for a specific search term."""
    params = urllib.parse.urlencode({"query_term": query, "limit": 10})
    url = f"{YTS_API_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("data", {}).get("movies", [])
    except Exception:
        return []


def fetch_yts_movie_data(title: str) -> Optional[Dict[str, Any]]:
    """Search YTS API for a movie and extract synopsis, ratings, and download links."""
    clean_query = re.sub(r"[^\w\s]", " ", title).strip()
    movies = _query_yts(clean_query)

    # Fallback: if query started with a number like "12 Monkeys", try "Twelve Monkeys"
    if not movies:
        tokens = clean_query.split()
        if tokens and tokens[0] in NUM_MAP:
            alt_query = NUM_MAP[tokens[0]] + " " + " ".join(tokens[1:])
            movies = _query_yts(alt_query)

    if not movies:
        return None

    # Pick the movie with highest title similarity to avoid false matches
    target_lower = title.lower()
    best_movie = None
    best_score = -1.0

    for m in movies:
        m_title = m.get("title", "").lower()
        score = difflib.SequenceMatcher(None, target_lower, m_title).ratio()
        if score > best_score:
            best_score = score
            best_movie = m

    # Require minimum similarity to avoid matching completely different movies
    if best_score < 0.65 or not best_movie:
        return None

    torrents_list = []
    for t in best_movie.get("torrents", []):
        q = t.get("quality", "")
        t_hash = t.get("hash", "")
        t_url = t.get("url", "")
        size = t.get("size", "")
        magnet = build_magnet_uri(t_hash, best_movie.get("title", title), q) if t_hash else None
        torrents_list.append({
            "quality": q,
            "type": t.get("type", "WEB"),
            "size": size,
            "url": t_url,
            "magnet": magnet,
        })

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


def fetch_eztv_torrents(imdb_id: str) -> List[Dict[str, Any]]:
    """Fetch TV series torrents from EZTV API using clean numeric IMDb ID."""
    clean_id = re.sub(r"[^\d]", "", imdb_id)
    if not clean_id:
        return []

    url = f"{EZTV_API_URL}?imdb_id={clean_id}&limit=10"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            torrents = data.get("torrents", [])
            results = []
            for t in torrents:
                results.append({
                    "title": t.get("title", ""),
                    "season": t.get("season"),
                    "episode": t.get("episode"),
                    "size": t.get("size_bytes"),
                    "url": t.get("torrent_url"),
                    "magnet": t.get("magnet_url"),
                })
            return results
    except Exception:
        return []


def _inspect_wiki_page(candidate: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Helper to query a single Wikipedia title and extract summary, poster, and media type."""
    encoded = urllib.parse.quote(candidate.replace(" ", "_"))
    url = f"{WIKI_SUMMARY_URL}/{encoded}"
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("type") == "disambiguation":
                return None, None, None

            extract = data.get("extract")
            desc = data.get("description", "")
            image_url = (
                data.get("thumbnail", {}).get("source")
                or data.get("originalimage", {}).get("source")
            )
            cleaned = None
            if extract and len(extract.strip()) > 20:
                cleaned = re.sub(r"\s+", " ", extract).strip()

            if "refer to:" in (cleaned or "") or "may refer to:" in (cleaned or ""):
                return None, None, None

            text_to_check = f"{desc} {cleaned or ''}"
            detected_type = None
            if TV_TYPE_PATTERNS.search(text_to_check) and not MOVIE_TYPE_PATTERNS.search(desc):
                detected_type = "tv"
            elif MOVIE_TYPE_PATTERNS.search(text_to_check):
                detected_type = "movie"

            return cleaned, image_url, detected_type
    except Exception:
        return None, None, None


def search_wikipedia_media_title(title: str) -> Tuple[Optional[str], Optional[str]]:
    """Search Wikipedia for title to find TV series or Film pages."""
    try:
        url = f"{WIKI_SEARCH_URL}&srsearch={urllib.parse.quote(title)}&srlimit=6"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("query", {}).get("search", [])
            for r in results:
                t = r.get("title", "")
                clean_t = re.sub(r"\s*\([^)]*\)", "", t).strip().lower()
                if clean_t == title.lower() or t.lower().startswith(title.lower() + " ("):
                    if re.search(r"\b(tv series|television series|miniseries|series)\b", t, re.I):
                        return t, "tv"
                    if re.search(r"\b(film|movie)\b", t, re.I):
                        return t, "movie"
    except Exception:
        pass
    return None, None


def fetch_wikipedia_details(
    title: str, media_type: Optional[str] = None
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Fetch a concise overview, poster image, and media type ('tv' or 'movie') from Wikipedia."""
    if media_type == "tv":
        candidates = [f"{title} (TV series)", f"{title} (miniseries)", f"{title} (series)", title]
        for cand in candidates:
            s, p, dt = _inspect_wiki_page(cand)
            if s or p:
                return s, p, dt or "tv"
        return None, None, "tv"

    if media_type == "movie":
        candidates = [title, f"{title} (film)", f"{title} (movie)"]
        for cand in candidates:
            s, p, dt = _inspect_wiki_page(cand)
            if s or p:
                return s, p, dt or "movie"
        return None, None, "movie"

    # When media_type is unknown:
    # 1. First check the direct title
    summary, poster, detected_type = _inspect_wiki_page(title)
    if detected_type:
        return summary, poster, detected_type

    # 2. Check (film) candidate
    for cand in [f"{title} (film)", f"{title} (movie)"]:
        s, p, dt = _inspect_wiki_page(cand)
        if dt == "movie" or (s and MOVIE_TYPE_PATTERNS.search(s[:200])):
            return s, p, "movie"

    # 3. Check TV candidates
    for cand in [f"{title} (TV series)", f"{title} (miniseries)", f"{title} (series)"]:
        s, p, dt = _inspect_wiki_page(cand)
        if dt == "tv" or (s and TV_TYPE_PATTERNS.search(s[:200])):
            return s, p, "tv"
        if s or p:
            return s, p, "tv"

    # 4. Search API fallback (e.g. 'Fallout (American TV series)')
    hit_title, hit_type = search_wikipedia_media_title(title)
    if hit_title:
        s, p, dt = _inspect_wiki_page(hit_title)
        if s or p:
            return s, p, dt or hit_type

    # 5. Direct summary fallback if available
    if summary or poster:
        return summary, poster, detected_type

    return None, None, None


def fetch_wikipedia_summary(title: str, media_type: Optional[str] = None) -> Optional[str]:
    """Fetch a concise 2-3 sentence overview from Wikipedia's free REST API."""
    summary, _, _ = fetch_wikipedia_details(title, media_type)
    return summary


def fetch_arabic_wikipedia_summary(title: str, media_type: Optional[str] = None) -> Optional[str]:
    """Fetch native Arabic plot synopsis from Arabic Wikipedia."""
    candidates = []
    if media_type == "tv":
        candidates.extend([f"{title} (TV series)", f"{title} (series)", title])
    elif media_type == "movie":
        candidates.extend([f"{title} (film)", f"{title} (movie)", title])
    else:
        candidates.extend([f"{title} (film)", f"{title} (TV series)", title])

    # Method 1: Interlanguage link resolution via English Wikipedia API
    for cand in candidates:
        try:
            enc = urllib.parse.quote(cand.replace(" ", "_"))
            langlink_url = (
                f"https://en.wikipedia.org/w/api.php?action=query&prop=langlinks&lllang=ar"
                f"&titles={enc}&redirects=1&format=json"
            )
            req = urllib.request.Request(langlink_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                pages = data.get("query", {}).get("pages", {})
                for p_id, p_val in pages.items():
                    ll = p_val.get("langlinks", [])
                    if ll and len(ll) > 0 and ll[0].get("*"):
                        ar_title = ll[0]["*"]
                        sum_url = f"{WIKI_AR_SUMMARY_URL}/{urllib.parse.quote(ar_title.replace(' ', '_'))}"
                        req_ar = urllib.request.Request(sum_url, headers=HEADERS)
                        with urllib.request.urlopen(req_ar, timeout=4) as resp_ar:
                            ar_data = json.loads(resp_ar.read().decode("utf-8"))
                            extract = ar_data.get("extract")
                            if extract and len(extract.strip()) > 15:
                                return re.sub(r"\s+", " ", extract).strip()
        except Exception:
            continue

    # Method 2: Direct lookup on Arabic Wikipedia
    for cand in [title, f"{title} (فيلم)", f"{title} (مسلسل)"]:
        try:
            enc = urllib.parse.quote(cand.replace(" ", "_"))
            sum_url = f"{WIKI_AR_SUMMARY_URL}/{enc}"
            req = urllib.request.Request(sum_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=3) as resp:
                ar_data = json.loads(resp.read().decode("utf-8"))
                extract = ar_data.get("extract")
                if extract and len(extract.strip()) > 15:
                    return re.sub(r"\s+", " ", extract).strip()
        except Exception:
            continue

    return None


def enrich_single_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single movie or series item with synopsis, year, and download links."""
    enriched = dict(item)
    title = item.get("title", "")
    known_type = item.get("type")

    # 1. Fetch Wikipedia details & detect media type (tv vs movie)
    wiki_summary, wiki_poster, detected_type = fetch_wikipedia_details(
        title, media_type=known_type
    )
    final_type = known_type or detected_type

    yts_data = None
    # 2. Search YTS for movie torrents, year, rating, and synopsis ONLY if not TV series
    if final_type != "tv":
        yts_data = fetch_yts_movie_data(title)
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

    # 3. Check EZTV if imdb_code is available and item is a TV show
    if enriched.get("imdb_code") and final_type == "tv":
        eztv_torrents = fetch_eztv_torrents(enriched["imdb_code"])
        if eztv_torrents:
            enriched["torrents"] = eztv_torrents

    # 4. Fill in missing synopsis or poster from Wikipedia
    if not enriched.get("synopsis") and wiki_summary:
        enriched["synopsis"] = wiki_summary
    if not enriched.get("poster_url") and wiki_poster:
        enriched["poster_url"] = wiki_poster

    # 5. Finalize media type: default to movie if still undetermined
    if not final_type:
        final_type = "movie"

    enriched["type"] = final_type

    # 6. Fetch native Arabic plot overview
    if not enriched.get("synopsis_ar"):
        ar_summary = fetch_arabic_wikipedia_summary(title, media_type=final_type)
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

    return enriched


def enrich_media_items(
    items: List[Dict[str, Any]],
    max_workers: int = 10,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Enrich a list of items concurrently using a thread pool for maximum speed."""
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
                enriched_list[idx] = future.result()
            except Exception as e:
                logger.debug("Enrichment error on item %d: %s", idx, e)
                enriched_list[idx] = items[idx]

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return [item for item in enriched_list if item is not None]


def search_media_database(query: str, tmdb_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Search for movies and TV series across YTS, Wikipedia, and TMDB.
    
    Returns structured media cards with torrents, magnet links, posters, and bilingual synopses.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    results: List[Dict[str, Any]] = []
    seen_titles = set()

    # 1. Search YTS for Movies (returns multiple matches with magnets)
    try:
        yts_search_url = f"{YTS_API_URL}?query_term={urllib.parse.quote(clean_q)}&limit=12"
        req = urllib.request.Request(yts_search_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            movies = data.get("data", {}).get("movies", [])
            for m in movies:
                m_title = m.get("title", "").strip()
                if not m_title:
                    continue
                seen_titles.add(m_title.lower())

                torrents_list = []
                for t in m.get("torrents", []):
                    q = t.get("quality", "")
                    t_hash = t.get("hash", "")
                    t_url = t.get("url", "")
                    size = t.get("size", "")
                    magnet = build_magnet_uri(t_hash, m_title, q) if t_hash else None
                    torrents_list.append({
                        "quality": q,
                        "type": t.get("type", "WEB"),
                        "size": size,
                        "url": t_url,
                        "magnet": magnet,
                    })

                summary = m.get("summary") or m.get("synopsis") or m.get("description_full") or ""
                if summary:
                    summary = summary.replace("\n", " ").strip()

                m_genres = m.get("genres") or []
                if not m_genres and summary:
                    m_genres = detect_genres_from_text(summary)
                if not m_genres:
                    m_genres = ["Other"]

                results.append({
                    "title": m_title,
                    "type": "movie",
                    "genres": m_genres,
                    "primary_genre": m_genres[0] if m_genres else "Other",
                    "year": str(m.get("year", "")) if m.get("year") else None,
                    "rating": m.get("rating"),
                    "poster_url": m.get("large_cover_image") or m.get("medium_cover_image"),
                    "synopsis": summary,
                    "synopsis_ar": None,
                    "torrents": torrents_list,
                    "url": m.get("url"),
                    "imdb_code": m.get("imdb_code"),
                })
    except Exception as e:
        logger.debug("YTS search error: %s", e)

    # 2. Search Wikipedia via OpenSearch (great for TV series and unlisted films)
    try:
        wiki_search_url = (
            f"https://en.wikipedia.org/w/api.php?action=opensearch"
            f"&search={urllib.parse.quote(clean_q)}&limit=6&namespace=0&format=json"
        )
        req = urllib.request.Request(wiki_search_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            wiki_titles = data[1] if len(data) > 1 else []
            for wt in wiki_titles:
                clean_wt = re.sub(r"\s*\([^)]*\)", "", wt).strip()
                if clean_wt.lower() in seen_titles:
                    continue
                seen_titles.add(clean_wt.lower())

                w_summary, w_poster, w_type = fetch_wikipedia_details(wt)
                if w_summary or w_poster:
                    media_type = w_type or ("tv" if "series" in wt.lower() or "season" in wt.lower() else "movie")
                    w_genres = detect_genres_from_text(w_summary) if w_summary else []
                    if not w_genres:
                        w_genres = ["Drama"] if media_type == "tv" else ["Other"]

                    results.append({
                        "title": clean_wt,
                        "type": media_type,
                        "genres": w_genres,
                        "primary_genre": w_genres[0] if w_genres else "Other",
                        "year": None,
                        "rating": None,
                        "poster_url": w_poster,
                        "synopsis": w_summary,
                        "synopsis_ar": None,
                        "torrents": [],
                        "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(wt.replace(' ', '_'))}",
                        "imdb_code": None,
                    })
    except Exception as e:
        logger.debug("Wikipedia search error: %s", e)

    # 3. Concurrently enrich Arabic synopses for all results
    def enrich_arabic(res: Dict[str, Any]):
        try:
            ar_sum = fetch_arabic_wikipedia_summary(res["title"], media_type=res.get("type"))
            if ar_sum:
                res["synopsis_ar"] = ar_sum
        except Exception:
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(enrich_arabic, results))

    # 4. TMDB Enrichment if key provided
    if tmdb_key:
        try:
            from tmdb import enrich_items_with_tmdb
            results = enrich_items_with_tmdb(results, tmdb_key)
        except Exception as e:
            logger.debug("TMDB search enrichment error: %s", e)

    return results
