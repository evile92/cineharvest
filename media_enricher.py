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
from typing import Dict, Any, List, Optional, Callable

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
HEADERS = {"User-Agent": "GoogleCollectionMediaExtractor/2.0 (OpenSource)"}

# Number-to-word translation for query fallback
NUM_MAP = {
    "1": "one", "2": "two", "3": "three", "4": "four", "5": "five",
    "6": "six", "7": "seven", "8": "eight", "9": "nine", "10": "ten",
    "12": "twelve", "28": "twenty-eight",
}


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
    if best_score < 0.45 or not best_movie:
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


def fetch_wikipedia_summary(title: str, media_type: Optional[str] = None) -> Optional[str]:
    """Fetch a concise 2-3 sentence overview from Wikipedia's free REST API."""
    candidates = [title]
    if media_type == "tv":
        candidates.extend([f"{title} (TV series)", f"{title} (series)"])
    elif media_type == "movie":
        candidates.extend([f"{title} (film)", f"{title} (movie)"])
    else:
        candidates.extend([f"{title} (film)", f"{title} (TV series)"])

    for candidate in candidates:
        encoded = urllib.parse.quote(candidate.replace(" ", "_"))
        url = f"{WIKI_SUMMARY_URL}/{encoded}"
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                extract = data.get("extract")
                if extract and len(extract.strip()) > 20:
                    cleaned = re.sub(r"\s+", " ", extract).strip()
                    return cleaned
        except Exception:
            continue

    return None


def enrich_single_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Enrich a single movie or series item with synopsis, year, and download links."""
    enriched = dict(item)
    title = item.get("title", "")
    known_type = item.get("type")

    # 1. Search YTS for movie torrents, year, rating, and synopsis
    if known_type != "tv":
        yts_data = fetch_yts_movie_data(title)
        if yts_data:
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
            if not enriched.get("type"):
                enriched["type"] = "movie"

    # 2. Check EZTV if imdb_code is available and item is a show
    if enriched.get("imdb_code") and enriched.get("type") == "tv":
        eztv_torrents = fetch_eztv_torrents(enriched["imdb_code"])
        if eztv_torrents:
            enriched["torrents"] = eztv_torrents

    # 3. If no synopsis yet, query Wikipedia (ideal for TV series or unindexed films)
    if not enriched.get("synopsis"):
        wiki_summary = fetch_wikipedia_summary(title, media_type=known_type or enriched.get("type"))
        if wiki_summary:
            enriched["synopsis"] = wiki_summary

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
