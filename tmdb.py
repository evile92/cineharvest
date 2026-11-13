"""Optional TMDB (The Movie Database) API integration.

Enriches extracted titles with release year, vote average, poster image URL,
genres, and synopses (EN/AR) for export and UI display.
"""

import concurrent.futures
import difflib
import logging
import threading
from typing import Dict, Any, List, Optional, Callable

import requests
from cleaner import extract_title_and_year

logger = logging.getLogger("google_collection_extractor")

TMDB_SEARCH_URL = "https://api.themoviedb.org/3/search/multi"
_thread_local = threading.local()


def _get_session() -> requests.Session:
    """Return a thread-local requests.Session for HTTP keep-alive connection pooling."""
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": "GoogleCollectionExtractor/2.0"})
        _thread_local.session = sess
    return sess


def _search_tmdb_multi(
    title: str,
    api_key: str,
    language: str = "en-US",
    expected_type: Optional[str] = None,
    expected_year: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Query TMDB /search/multi and select best matching movie/tv result."""
    if not api_key or not title:
        return None

    clean_title, parsed_year = extract_title_and_year(title)
    target_year = expected_year or parsed_year

    params = {
        "api_key": api_key,
        "query": clean_title,
        "include_adult": "false",
        "language": language,
    }

    try:
        resp = _get_session().get(TMDB_SEARCH_URL, params=params, timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        raw_results = [
            r for r in data.get("results", [])
            if r.get("media_type") in ("movie", "tv")
        ]
        if not raw_results:
            return None

        target_lower = clean_title.lower()
        best_cand = None
        best_score = -1.0

        for cand in raw_results:
            mtype = cand.get("media_type")
            names = [
                cand.get("title") or "",
                cand.get("original_title") or "",
                cand.get("name") or "",
                cand.get("original_name") or "",
            ]
            sim = max(
                difflib.SequenceMatcher(None, target_lower, n.strip().lower()).ratio()
                for n in names if n.strip()
            ) if any(n.strip() for n in names) else 0.0

            release_date = cand.get("release_date") or cand.get("first_air_date") or ""
            cand_year = release_date.split("-")[0] if release_date else None

            score = sim
            if expected_type and mtype == expected_type:
                score += 0.15
            if target_year and cand_year:
                if cand_year == target_year:
                    score += 0.20
                elif cand_year.isdigit() and target_year.isdigit() and abs(int(cand_year) - int(target_year)) > 1:
                    score -= 0.10

            if score > best_score:
                best_score = score
                best_cand = cand

        if not best_cand or best_score < 0.55:
            return None

        release_date = best_cand.get("release_date") or best_cand.get("first_air_date") or ""
        year = release_date.split("-")[0] if release_date else None
        poster_path = best_cand.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

        rating = best_cand.get("vote_average")
        if rating:
            rating = round(float(rating), 1)

        return {
            "year": year,
            "rating": rating,
            "type": best_cand.get("media_type"),
            "poster_url": poster_url,
            "overview": (best_cand.get("overview") or "").strip() or None,
        }
    except Exception as e:
        logger.debug("TMDB lookup failed for '%s': %s", title, e)
        return None


def fetch_tmdb_details(
    title: str,
    api_key: str,
    expected_type: Optional[str] = None,
    expected_year: Optional[str] = None,
    lang: str = "en",
) -> Optional[Dict[str, Any]]:
    """Search TMDB for a movie or TV series title and return matched metadata (with optional Arabic synopsis)."""
    meta = _search_tmdb_multi(
        title=title,
        api_key=api_key,
        language="en-US",
        expected_type=expected_type,
        expected_year=expected_year,
    )
    if not meta:
        return None

    if lang == "ar":
        ar_meta = _search_tmdb_multi(
            title=title,
            api_key=api_key,
            language="ar-SA",
            expected_type=expected_type,
            expected_year=expected_year,
        )
        if ar_meta and ar_meta.get("overview"):
            meta["overview_ar"] = ar_meta["overview"]

    return meta


def _enrich_single_tmdb(item: Dict[str, Any], api_key: str, lang: str = "en") -> Dict[str, Any]:
    """Enrich a single media item dictionary with TMDB metadata."""
    title = item.get("title", "")
    metadata = fetch_tmdb_details(
        title,
        api_key,
        expected_type=item.get("type"),
        expected_year=item.get("year"),
        lang=lang,
    )
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
            if not updated.get("synopsis"):
                updated["synopsis"] = metadata["overview"]
        if metadata.get("overview_ar"):
            updated["synopsis_ar"] = metadata["overview_ar"]
    return updated


def enrich_items_with_tmdb(
    items: List[Dict[str, Any]],
    api_key: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    max_workers: int = 8,
    lang: str = "en",
) -> List[Dict[str, Any]]:
    """Enrich a list of extracted titles concurrently with TMDB metadata."""
    total = len(items)
    if not total or not api_key:
        return items

    enriched_list: List[Optional[Dict[str, Any]]] = [None] * total
    completed = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_enrich_single_tmdb, item, api_key, lang): idx
            for idx, item in enumerate(items)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                enriched_list[idx] = future.result()
            except Exception as e:
                logger.debug("TMDB enrichment error on item %d: %s", idx, e)
                enriched_list[idx] = items[idx]

            completed += 1
            if progress_callback:
                progress_callback(completed, total)

    return [item for item in enriched_list if item is not None]
