"""YouTube media extraction and download engine for CineHarvest.

Supports:
- Single video and full playlist metadata extraction.
- Audio extraction in MP3 (320k, 192k, 128k), M4A, and WAV.
- Video downloads in MP4 across multiple resolutions (1080p, 720p, 480p, 360p, Best).
- Automatic FFmpeg discovery via imageio-ffmpeg or system PATH.
- Real-time progress monitoring and ZIP packaging for playlist downloads.
"""

import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple

import yt_dlp

logger = logging.getLogger("google_collection_extractor")


def get_ffmpeg_path() -> Optional[str]:
    """Locate FFmpeg executable from imageio-ffmpeg package or system PATH."""
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg

    return None


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe usage as a cross-platform filename."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:120] if clean else "media_file"


def is_playlist_url(url: str) -> bool:
    """Check if the provided URL represents a YouTube playlist."""
    if not url:
        return False
    u = url.lower()
    return "playlist?list=" in u or ("list=" in u and "watch?v=" not in u)


YOUTUBE_CLIENT_STRATEGIES = [
    ["android", "web"],
    ["web", "android"],
    ["mweb", "android"],
]


def resolve_cookiefile(
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Optional[str]:
    """Resolve cookie file path from argument, content string, env vars, or standard locations."""
    if cookies_content and cookies_content.strip():
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_cookies.txt", encoding="utf-8")
        tmp.write(cookies_content.strip())
        tmp.close()
        return tmp.name

    if cookiefile and os.path.exists(cookiefile):
        return cookiefile

    # Check environment variables
    env_cookies = os.getenv("YOUTUBE_COOKIES")
    if env_cookies and env_cookies.strip():
        tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix="_cookies.txt", encoding="utf-8")
        tmp.write(env_cookies.strip())
        tmp.close()
        return tmp.name

    env_path = os.getenv("YOUTUBE_COOKIEFILE")
    if env_path and os.path.exists(env_path):
        return env_path

    # Check project standard locations
    for loc in [Path("cookies.txt"), Path("auth/cookies.txt"), Path(".streamlit/cookies.txt")]:
        if loc.exists():
            return str(loc.resolve())

    return None


def extract_media_info(
    url: str,
    is_playlist: Optional[bool] = None,
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract metadata for a single YouTube video or an entire playlist without downloading."""
    if is_playlist is None:
        is_playlist = is_playlist_url(url)

    ffmpeg_exe = get_ffmpeg_path()
    resolved_cookies = resolve_cookiefile(cookiefile, cookies_content)
    info = None
    last_err: Optional[Exception] = None

    strategies = [["default", "web", "android"]] + YOUTUBE_CLIENT_STRATEGIES if resolved_cookies else YOUTUBE_CLIENT_STRATEGIES

    for client_strategy in strategies:
        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "js_runtimes": {"node": {}, "deno": {}},
            "extractor_args": {
                "youtube": {
                    "player_client": client_strategy,
                }
            },
        }
        if resolved_cookies:
            ydl_opts["cookiefile"] = resolved_cookies
        if ffmpeg_exe:
            ydl_opts["ffmpeg_location"] = ffmpeg_exe

        if is_playlist:
            ydl_opts["extract_flat"] = "in_playlist"
        else:
            ydl_opts["extract_flat"] = False

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    break
        except Exception as e:
            last_err = e
            continue

    if not info:
        if last_err:
            raise last_err
        raise ValueError("Failed to retrieve media information from YouTube.")

    # Check if the extracted info is indeed a playlist
    entries = info.get("entries")
    if entries is not None:
        # Playlist structure
        clean_entries = []
        for idx, entry in enumerate(entries, 1):
            if not entry:
                continue
            entry_url = entry.get("url") or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else None)
            clean_entries.append({
                "index": idx,
                "id": entry.get("id"),
                "title": entry.get("title", f"Video {idx}"),
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader", "Unknown"),
                "url": entry_url,
            })

        thumbnail = info.get("thumbnails", [{}])[-1].get("url") if info.get("thumbnails") else None
        if not thumbnail and clean_entries:
            first_id = clean_entries[0].get("id")
            if first_id:
                thumbnail = f"https://i.ytimg.com/vi/{first_id}/hqdefault.jpg"

        return {
            "is_playlist": True,
            "title": info.get("title", "YouTube Playlist"),
            "uploader": info.get("uploader") or info.get("channel") or "Unknown Channel",
            "thumbnail": thumbnail,
            "video_count": len(clean_entries),
            "entries": clean_entries,
        }

    # Single video structure
    thumbnail = info.get("thumbnail")
    if not thumbnail and info.get("thumbnails"):
        thumbnail = info.get("thumbnails")[-1].get("url")

    return {
        "is_playlist": False,
        "id": info.get("id"),
        "title": info.get("title", "YouTube Video"),
        "uploader": info.get("uploader") or info.get("channel") or "Unknown Channel",
        "duration": info.get("duration", 0),
        "view_count": info.get("view_count"),
        "thumbnail": thumbnail,
        "url": url,
    }


def download_single_video(
    url: str,
    output_dir: Path,
    media_type: str = "video",  # "video" or "audio"
    media_format: str = "mp4",  # "mp4", "mp3", "m4a", "wav"
    quality: str = "720p",      # "1080p", "720p", "480p", "360p", "best" or "320k", "192k", "128k"
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Path:
    """Download a single YouTube video or extract its audio into the target directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_path()
    resolved_cookies = resolve_cookiefile(cookiefile, cookies_content)

    outtmpl = str(output_dir / "%(title).120s.%(ext)s")

    ydl_opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "js_runtimes": {"node": {}, "deno": {}},
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            }
        },
    }

    if resolved_cookies:
        ydl_opts["cookiefile"] = resolved_cookies

    if ffmpeg_exe:
        ydl_opts["ffmpeg_location"] = ffmpeg_exe

    if media_type == "audio":
        codec = media_format.lower()
        if codec not in ["mp3", "m4a", "wav", "aac"]:
            codec = "mp3"

        bitrate = quality.replace("k", "").strip() if quality else "192"
        if not bitrate.isdigit():
            bitrate = "192"

        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": bitrate,
        }]
    else:
        # Video format logic
        q_lower = quality.lower()
        if "1080" in q_lower:
            format_str = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best"
        elif "720" in q_lower:
            format_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/bestvideo+bestaudio/best"
        elif "480" in q_lower:
            format_str = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/bestvideo+bestaudio/best"
        elif "360" in q_lower:
            format_str = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=360]+bestaudio/best[height<=360]/bestvideo+bestaudio/best"
        else:
            format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"

        ydl_opts["format"] = format_str
        ydl_opts["merge_output_format"] = "mp4"

    # Execute download
    downloaded_files: List[str] = []

    def tracking_hook(d: Dict[str, Any]):
        if d.get("status") == "finished":
            f_path = d.get("filename")
            if f_path:
                downloaded_files.append(f_path)
        if progress_hook:
            progress_hook(d)

    ydl_opts["progress_hooks"] = [tracking_hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        meta = ydl.extract_info(url, download=True)
        # Identify the output filename from downloaded files or meta
        expected_filename = ydl.prepare_filename(meta)
        if media_type == "audio":
            base = os.path.splitext(expected_filename)[0]
            expected_filename = f"{base}.{media_format.lower()}"

        final_path = Path(expected_filename)
        if final_path.exists():
            return final_path

        if downloaded_files:
            last_file = Path(downloaded_files[-1])
            if media_type == "audio":
                base = last_file.with_suffix(f".{media_format.lower()}")
                if base.exists():
                    return base
            if last_file.exists():
                return last_file

        # Check directory for most recent matching file
        files = list(output_dir.glob("*.*"))
        if files:
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            return files[0]

        raise FileNotFoundError("Could not verify downloaded file on disk.")


def download_playlist_media(
    playlist_url: str,
    output_dir: Path,
    media_type: str = "audio",
    media_format: str = "mp3",
    quality: str = "192k",
    selected_indices: Optional[List[int]] = None,
    item_callback: Optional[Callable[[int, int, str], None]] = None,
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Tuple[Path, List[Path]]:
    """Download multiple videos from a playlist, convert formats, and compress into a single ZIP archive."""
    playlist_info = extract_media_info(
        playlist_url,
        is_playlist=True,
        cookiefile=cookiefile,
        cookies_content=cookies_content,
    )
    entries = playlist_info.get("entries", [])
    playlist_title = sanitize_filename(playlist_info.get("title", "YouTube_Playlist"))

    batch_dir = output_dir / playlist_title
    batch_dir.mkdir(parents=True, exist_ok=True)

    target_entries = entries
    if selected_indices:
        selected_set = set(selected_indices)
        target_entries = [e for e in entries if e["index"] in selected_set]

    total = len(target_entries)
    downloaded_paths: List[Path] = []

    for idx, entry in enumerate(target_entries, 1):
        v_url = entry.get("url")
        v_title = entry.get("title", f"Track {idx}")
        if item_callback:
            item_callback(idx, total, v_title)

        try:
            downloaded = download_single_video(
                url=v_url,
                output_dir=batch_dir,
                media_type=media_type,
                media_format=media_format,
                quality=quality,
                progress_hook=progress_hook,
                cookiefile=cookiefile,
                cookies_content=cookies_content,
            )
            downloaded_paths.append(downloaded)
        except Exception as e:
            logger.warning("Failed to download playlist item %s (%s): %s", idx, v_title, e)

    if not downloaded_paths:
        raise RuntimeError("No files were successfully downloaded from the playlist.")

    # Create ZIP archive
    zip_path = output_dir / f"{playlist_title}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_f:
        for f in downloaded_paths:
            if f.exists():
                zip_f.write(f, arcname=f.name)

    return zip_path, downloaded_paths
