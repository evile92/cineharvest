"""YouTube media extraction and download engine for CineHarvest.

Supports:
- Single video and full playlist metadata extraction.
- Cookie-aware multi-client fallback (prioritizing cookie-compatible clients when cookies exist).
- Process-isolated temporary cookie handling to prevent cross-user leakage/races.
- Audio extraction in MP3 (320k, 192k, 128k), M4A, and WAV.
- Video downloads in MP4 (1080p, 720p, 480p, 360p, Best) with optional soft subtitles.
- Automatic FFmpeg discovery via imageio-ffmpeg or system PATH.
- Real-time progress monitoring and ZIP packaging for playlist downloads.
"""

import logging
import os
import re
import shutil
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Tuple

import yt_dlp

logger = logging.getLogger("google_collection_extractor")

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}

COOKIED_CLIENT_STRATEGIES = [
    ["web", "default"],
    ["mweb", "web"],
    ["default", "web", "android"],
]

ANON_CLIENT_STRATEGIES = [
    ["android", "web"],
    ["web", "android"],
    ["mweb", "android"],
    ["tv", "web"],
]


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


def is_valid_youtube_url(url: str) -> bool:
    """Verify URL points to a valid YouTube host with http/https scheme."""
    if not url or not url.strip():
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        return host in YOUTUBE_HOSTS
    except Exception:
        return False


def has_video_and_playlist(url: str) -> bool:
    """Check whether URL contains both a single video identifier and a playlist parameter."""
    if not url:
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
        qs = urllib.parse.parse_qs(parsed.query)
        has_list = bool(qs.get("list"))
        has_vid = bool(qs.get("v")) or (parsed.hostname or "").lower().endswith("youtu.be")
        return has_list and has_vid
    except Exception:
        return False


def is_playlist_url(url: str) -> bool:
    """Check if the provided URL primarily represents a YouTube playlist."""
    if not url:
        return False
    u = url.lower()
    return "playlist?list=" in u or ("list=" in u and "watch?v=" not in u and "youtu.be/" not in u)


def cleanup_download_dir(directory: Path) -> None:
    """Remove old files and subdirectories inside a temporary download folder."""
    if not directory or not directory.exists():
        return
    for child in directory.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            pass


def resolve_cookiefile(
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Tuple[Optional[str], bool]:
    """Resolve cookie file path and return (path, is_temporary_file).

    Writes cookie string content into an isolated temporary file per call so concurrent
    sessions never overwrite each other's credentials.
    """
    if cookies_content and cookies_content.strip():
        tf = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="cineharvest_ck_",
            delete=False,
            encoding="utf-8",
        )
        try:
            tf.write(cookies_content.strip())
            tf.flush()
        finally:
            tf.close()
        return tf.name, True

    if cookiefile and os.path.exists(cookiefile):
        return cookiefile, False

    env_cookies = os.getenv("YOUTUBE_COOKIES")
    if env_cookies and env_cookies.strip():
        tf = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="cineharvest_ck_",
            delete=False,
            encoding="utf-8",
        )
        try:
            tf.write(env_cookies.strip())
            tf.flush()
        finally:
            tf.close()
        return tf.name, True

    env_path = os.getenv("YOUTUBE_COOKIEFILE")
    if env_path and os.path.exists(env_path):
        return env_path, False

    for loc in [Path("cookies.txt"), Path("auth/cookies.txt"), Path(".streamlit/cookies.txt")]:
        if loc.exists():
            return str(loc.resolve()), False

    return None, False


def _cleanup_temp_cookie(cookie_path: Optional[str], is_temp: bool) -> None:
    """Safely remove temporary cookie file if it was dynamically created."""
    if is_temp and cookie_path:
        try:
            Path(cookie_path).unlink(missing_ok=True)
        except Exception:
            pass


def _client_strategies_for(has_cookies: bool) -> List[List[str]]:
    """Return ordered YouTube player_client fallback strategies depending on cookie presence."""
    return COOKIED_CLIENT_STRATEGIES if has_cookies else ANON_CLIENT_STRATEGIES


def extract_media_info(
    url: str,
    is_playlist: Optional[bool] = None,
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract metadata for a single YouTube video or playlist without downloading."""
    if is_playlist is None:
        is_playlist = is_playlist_url(url)

    ffmpeg_exe = get_ffmpeg_path()
    resolved_cookies, is_temp_cookie = resolve_cookiefile(cookiefile, cookies_content)
    info = None
    last_err: Optional[Exception] = None

    try:
        for client_strategy in _client_strategies_for(bool(resolved_cookies)):
            ydl_opts: Dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "noplaylist": not is_playlist,
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
            ydl_opts["extract_flat"] = "in_playlist" if is_playlist else False

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        break
            except Exception as e:
                last_err = e
                continue
    finally:
        _cleanup_temp_cookie(resolved_cookies, is_temp_cookie)

    if not info:
        if last_err:
            raise last_err
        raise ValueError("Failed to retrieve media information from YouTube.")

    entries = info.get("entries")
    if entries is not None:
        clean_entries = []
        for idx, entry in enumerate(entries, 1):
            if not entry:
                continue
            entry_url = entry.get("url") or (
                f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else None
            )
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
            "url": url,
        }

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


def _build_video_format_string(quality: str) -> str:
    """Build yt-dlp format selector string for target MP4 video quality."""
    q_lower = (quality or "720p").lower()
    for res in ("1080", "720", "480", "360"):
        if res in q_lower:
            return (
                f"bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={res}]+bestaudio/best[height<={res}]/bestvideo+bestaudio/best"
            )
    return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"


def download_single_video(
    url: str,
    output_dir: Path,
    media_type: str = "video",
    media_format: str = "mp4",
    quality: str = "720p",
    progress_hook: Optional[Callable[[Dict[str, Any]], None]] = None,
    cookiefile: Optional[str] = None,
    cookies_content: Optional[str] = None,
    subtitles_langs: Optional[List[str]] = None,
) -> Path:
    """Download a single YouTube video or extract audio using cookie-aware fallback strategies."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_exe = get_ffmpeg_path()
    resolved_cookies, is_temp_cookie = resolve_cookiefile(cookiefile, cookies_content)
    outtmpl = str(output_dir / "%(title).120s.%(ext)s")

    last_err: Optional[Exception] = None

    try:
        for client_strategy in _client_strategies_for(bool(resolved_cookies)):
            downloaded_files: List[str] = []

            def tracking_hook(d: Dict[str, Any]):
                if d.get("status") == "finished":
                    f_path = d.get("filename")
                    if f_path:
                        downloaded_files.append(f_path)
                if progress_hook:
                    progress_hook(d)

            ydl_opts: Dict[str, Any] = {
                "outtmpl": outtmpl,
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "restrictfilenames": False,
                "js_runtimes": {"node": {}, "deno": {}},
                "extractor_args": {
                    "youtube": {
                        "player_client": client_strategy,
                    }
                },
                "progress_hooks": [tracking_hook],
            }

            if resolved_cookies:
                ydl_opts["cookiefile"] = resolved_cookies
            if ffmpeg_exe:
                ydl_opts["ffmpeg_location"] = ffmpeg_exe

            postprocessors: List[Dict[str, Any]] = []
            if media_type == "audio":
                codec = media_format.lower()
                if codec not in ["mp3", "m4a", "wav", "aac"]:
                    codec = "mp3"
                bitrate = quality.replace("k", "").strip() if quality else "192"
                if not bitrate.isdigit():
                    bitrate = "192"

                ydl_opts["format"] = "bestaudio/best"
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": codec,
                    "preferredquality": bitrate,
                })
            else:
                ydl_opts["format"] = _build_video_format_string(quality)
                ydl_opts["merge_output_format"] = "mp4"
                if subtitles_langs:
                    ydl_opts["writesubtitles"] = True
                    ydl_opts["writeautomaticsub"] = True
                    ydl_opts["subtitleslangs"] = subtitles_langs
                    ydl_opts["subtitlesformat"] = "srt/best"
                    postprocessors.append({"key": "FFmpegEmbedSubtitle"})

            if postprocessors:
                ydl_opts["postprocessors"] = postprocessors

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    meta = ydl.extract_info(url, download=True)
                    expected_filename = ydl.prepare_filename(meta)
                    if media_type == "audio":
                        base = os.path.splitext(expected_filename)[0]
                        expected_filename = f"{base}.{media_format.lower()}"
                    elif ydl_opts.get("merge_output_format") == "mp4":
                        base = os.path.splitext(expected_filename)[0]
                        mp4_candidate = Path(f"{base}.mp4")
                        if mp4_candidate.exists():
                            expected_filename = str(mp4_candidate)

                    final_path = Path(expected_filename)
                    if final_path.exists():
                        return final_path

                    if downloaded_files:
                        last_file = Path(downloaded_files[-1])
                        if media_type == "audio":
                            base_p = last_file.with_suffix(f".{media_format.lower()}")
                            if base_p.exists():
                                return base_p
                        if last_file.exists():
                            return last_file

                    files = [p for p in output_dir.glob("*.*") if not p.name.endswith((".part", ".ytdl"))]
                    if files:
                        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                        return files[0]

                    raise FileNotFoundError("Could not verify downloaded file on disk.")
            except Exception as e:
                last_err = e
                # Remove partial files before retrying next client strategy
                for part in output_dir.glob("*.part"):
                    part.unlink(missing_ok=True)
                continue

        if last_err:
            raise last_err
        raise RuntimeError("Failed to download YouTube media across all client strategies.")
    finally:
        _cleanup_temp_cookie(resolved_cookies, is_temp_cookie)


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
    subtitles_langs: Optional[List[str]] = None,
) -> Tuple[Path, List[Path]]:
    """Download selected videos from a playlist, convert formats, and bundle into a ZIP archive."""
    resolved_cookies, is_temp_cookie = resolve_cookiefile(cookiefile, cookies_content)
    try:
        playlist_info = extract_media_info(
            playlist_url,
            is_playlist=True,
            cookiefile=resolved_cookies,
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
                    cookiefile=resolved_cookies,
                    subtitles_langs=subtitles_langs,
                )
                downloaded_paths.append(downloaded)
            except Exception as e:
                logger.warning("Failed to download playlist item %s (%s): %s", idx, v_title, e)

        if not downloaded_paths:
            raise RuntimeError("No files were successfully downloaded from the playlist.")

        zip_path = output_dir / f"{playlist_title}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_f:
            for f in downloaded_paths:
                if f.exists():
                    zip_f.write(f, arcname=f.name)

        return zip_path, downloaded_paths
    finally:
        _cleanup_temp_cookie(resolved_cookies, is_temp_cookie)
