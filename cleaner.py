"""Data cleaning, normalization, and deduplication utilities.

Ensures clean titles, strict removal of Google UI artifacts, UTF-8
compatibility,
and order-preserving deduplication.
"""

import html
import re
from typing import List, Dict, Any, Optional

# Known Google UI / Navigation labels that must be discarded
GOOGLE_UI_LABELS = {
    "save to collection",
    "saved to collection",
    "more options",
    "more options for search watchlist",
    "more options for saved",
    "share",
    "share list",
    "remove",
    "remove from list",
    "saved",
    "watchlist",
    "search watchlist",
    "google apps",
    "sign in",
    "main menu",
    "go back",
    "close",
    "back",
    "more",
    "save",
    "items",
    "edit list",
    "add to list",
}

# Regex to detect and remove leading list numbering (e.g., "1. Movie", "02 - Show", "[3] Name", "(4) Film")
# Strictly requires numbering delimiters (. or - or ) or brackets) to avoid corrupting titles like "12 Monkeys" or "28 Days Later"
LEADING_NUMBER_PATTERN = re.compile(r"^(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,4}[\.\-\)])\s*")

# Regex to normalize multiple whitespace/newline sequences
WHITESPACE_PATTERN = re.compile(r"\s+")


def clean_title(raw_title: Optional[str]) -> str:
    """Clean and normalize a movie/series title.
    
    - Unescapes HTML entities (&amp;, &#39;, etc.)
    - Removes newlines, tabs, and excess whitespace
    - Removes leading list numbering (e.g. '1. ', '02 - ')
    - Discards Google UI buttons and labels
    - Preserves all Unicode, Arabic, and international characters
    """
    if not raw_title:
        return ""

    # Unescape HTML entities
    title = html.unescape(raw_title)

    # Normalize whitespace & newlines
    title = WHITESPACE_PATTERN.sub(" ", title).strip()

    # Discard if it starts with or matches a known UI label
    title_lower = title.lower()
    if title_lower in GOOGLE_UI_LABELS:
        return ""

    # Discard dynamic Google UI prefixes (e.g., "Shared with ...", "More options for ...")
    if title_lower.startswith("shared with ") or title_lower.startswith("more options for "):
        return ""

    # Strip leading numbers/bullets if any
    cleaned = LEADING_NUMBER_PATTERN.sub("", title).strip()

    # Re-check against UI labels after number stripping
    if cleaned.lower() in GOOGLE_UI_LABELS:
        return ""

    return cleaned


def is_valid_title(title: str) -> bool:
    """Check if the title is valid and not empty or pure punctuation."""
    if not title or len(title.strip()) < 1:
        return False
    # If title only consists of numbers or punctuation
    if not any(c.isalnum() for c in title):
        return False
    return True


def remove_duplicates_preserve_order(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate a list of items based on normalized title.
    
    Maintains the original order of first appearance.
    """
    seen = set()
    unique_items = []

    for item in items:
        title = item.get("title", "").strip()
        norm_key = title.lower()

        if norm_key and norm_key not in seen:
            seen.add(norm_key)
            unique_items.append(item)

    return unique_items


def detect_media_type(text_or_metadata: Optional[str]) -> Optional[str]:
    """Detect if the item is a movie or TV series based on unambiguous markers.
    
    Returns 'movie', 'tv', or None (never guesses).
    """
    if not text_or_metadata:
        return None

    meta_lower = text_or_metadata.lower()

    # Distinct TV markers
    tv_markers = [
        "tv series",
        "television series",
        "tv mini series",
        "tv show",
        "series",
        "مسلسل",
        "برنامج تلفزيوني",
    ]
    for marker in tv_markers:
        if marker in meta_lower:
            return "tv"

    # Distinct Movie markers
    movie_markers = [
        "film",
        "movie",
        "feature film",
        "فيلم",
    ]
    for marker in movie_markers:
        if marker in meta_lower:
            return "movie"

    # Return None when uncertain (zero guesswork rule)
    return None
