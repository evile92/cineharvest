"""Optional TMDB (The Movie Database) API integration.

Enriches extracted titles with release year, vote average, poster image URL,
genres, and overview for export to Letterboxd and comprehensive datasets.
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Dict, Any, List, Optional, Callable

logger = logging.getLogger("google_collection_extractor")

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/multi"


def fetch_tmdb_details(title: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Search TMDB for a movie or TV show title and return top result metadata."""
    if not api_key or not title:
        return None

    query_params = urllib.parse.urlencode({
        "api_key": api_key,
        "query": title,
        "include_adult": "false",
        "language": "en-US",
    })

    url = f"{TMDB_SEARCH_URL}?{query_params}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GoogleCollectionExtractor/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])

            if not results:
                return None

            top = results[0]
            media_type = top.get("media_type")  # "movie" or "tv"

            # Extract release year
            release_date = top.get("release_date") or top.get("first_air_date") or ""
            year = release_date.split("-")[0] if release_date else None

            poster_path = top.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

            return {
                "year": year,
                "rating": top.get("vote_average"),
                "type": media_type if media_type in ["movie", "tv"] else None,
                "poster_url": poster_url,
                "overview": top.get("overview"),
            }
    except Exception as e:
        logger.debug("TMDB lookup failed for '%s': %s", title, e)
        return None


def enrich_items_with_tmdb(
    items: List[Dict[str, Any]],
    api_key: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """Enrich a list of extracted titles with TMDB metadata."""
    enriched = []
    total = len(items)

    for idx, item in enumerate(items, 1):
        title = item.get("title", "")
        metadata = fetch_tmdb_details(title, api_key)

        updated = dict(item)
        if metadata:
            if metadata.get("year"):
                updated["year"] = metadata["year"]
            if metadata.get("rating"):
                updated["rating"] = metadata["rating"]
            if metadata.get("poster_url"):
                updated["poster_url"] = metadata["poster_url"]
            if metadata.get("type") and not updated.get("type"):
                updated["type"] = metadata["type"]
            if metadata.get("overview"):
                updated["overview"] = metadata["overview"]

        enriched.append(updated)

        if progress_callback:
            progress_callback(idx, total)

    return enriched
