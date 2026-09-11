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


def export_to_csv(items: List[Dict[str, Any]], path: Any) -> None:
    """Export items to standard CSV file format including synopsis and download links."""
    import csv
    from pathlib import Path
    
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    with open(target, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
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


def export_to_letterboxd_csv(items: List[Dict[str, Any]], path: Any) -> None:
    """Export items to official Letterboxd watchlist import CSV format.
    
    Letterboxd standard headers: Title, Year, URL
    """
    import csv
    from pathlib import Path
    
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
    with open(target, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Title", "Year", "URL"])
        for item in items:
            writer.writerow([
                item.get("title", ""),
                item.get("year") or "",
                item.get("url") or "",
            ])


def export_to_markdown(items: List[Dict[str, Any]], path: Any, collection_title: str = "Google Watchlist") -> None:
    """Export items to a formatted Markdown checklist with synopsis and download buttons."""
    from pathlib import Path
    
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    
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
        
        # Add Synopsis if available
        synopsis = item.get("synopsis")
        if synopsis:
            # Format clean blockquote
            short_syn = synopsis[:280] + ("..." if len(synopsis) > 280 else "")
            lines.append(f"  > 📖 *{short_syn}*")
            
        # Add Download Links if available
        torrents = item.get("torrents", [])
        if torrents:
            download_links = []
            for t in torrents[:3]:  # Top 3 qualities
                q = t.get("quality", "HD")
                size = f" ({t.get('size')})" if t.get("size") else ""
                if t.get("magnet"):
                    download_links.append(f"[🧲 Magnet {q}{size}]({t['magnet']})")
                elif t.get("url"):
                    download_links.append(f"[📥 Torrent {q}{size}]({t['url']})")
            if download_links:
                lines.append(f"  > 💾 **Downloads:** {' | '.join(download_links)}")
                
        lines.append("")  # Spacing
            
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
        
    lines.append("")
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


