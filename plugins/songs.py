"""
AUREX Songs Plugin — Full-Track Music Playback via YouTube
===========================================================
Plays full songs directly and completely free: yt-dlp searches YouTube and
downloads the best audio stream into the app's local media folder, and ffplay
plays the file headless. No Spotify account or API keys required.

Pipeline:
  1. SEARCH    yt-dlp queries YouTube (ytsearch) for the best match.
  2. DOWNLOAD  the audio stream is saved into <app>/temp_media/.
               Files are only ever written/overwritten, never deleted, so the
               plugin works inside the project's zero-deletion safety policy.
  3. PLAY      ffplay runs the local file with -nodisp -autoexit. Volume is
               applied through the -af audio filter (ffplay has no -volume
               command-line flag).

Dependencies:
  * yt-dlp (pip package — declared in requirements.txt). When missing the
    plugin reports exactly what to install instead of failing silently.
  * ffmpeg/ffplay — looked up on PATH first. On Windows, if absent, the
    plugin downloads a portable build once into <app>/vendor/ffmpeg and
    uses that, so the plugin works on a fresh machine with zero setup.
    (macOS / Linux: install ffmpeg yourself, e.g. `brew install ffmpeg`.)

Supported Actions:
  - play <song name>   / search <query>
  - pause music / resume music / stop music
  - next song (stop, then play the new query)
  - current song / what's playing
  - volume <0-100>, volume up, volume down
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

# ── Plugin metadata ───────────────────────────────────────────────────────────

PLUGIN = {
    "name": "songs",
    "description": (
        "Plays full songs and controls music playback for the user via YouTube. "
        "Use this tool when the user says 'play [song name]', 'search songs [query]', "
        "'search song [query]', 'play [song] by [artist]', 'koi gana sunao', 'pause music', "
        "'resume music', 'stop music', 'next song', 'skip', 'previous song', "
        "'what\\'s playing', 'current song', 'set volume to [number]', "
        "'volume up', or 'volume down'. "
        "This plugin streams and plays full tracks locally without any account "
        "or API keys needed. "
        "Do NOT use web_search, browser_control, or youtube_video to play music — always use "
        "this plugin instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: play, search, pause, resume, stop, next, previous, "
                    "current, volume"
                ),
            },
            "query": {
                "type": "STRING",
                "description": (
                    "Song name and/or artist to search for "
                    "(e.g. 'Arijit Singh top hits', 'Kesariya', etc.)."
                ),
            },
            "volume": {
                "type": "INTEGER",
                "description": (
                    "Volume level 0-100 (for action=volume). "
                    "Use -1 for 'volume up' or -2 for 'volume down'."
                ),
            },
        },
        "required": ["action"],
    },
    "behavior": "NON_BLOCKING",
}

# ── Paths & constants ─────────────────────────────────────────────────────────


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR   = _base_dir()
MEDIA_DIR  = BASE_DIR / "temp_media"          # downloaded tracks live here
VENDOR_DIR = BASE_DIR / "vendor" / "ffmpeg"    # auto-downloaded ffplay build

# Portable Windows build that ships ffplay (the GPL build includes it).
_VENDOR_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)

# ── Global Playback State ──────────────────────────────────────────────────────

_playback_proc: Optional[subprocess.Popen] = None
_current_track: dict = {}
_is_paused: bool = False
_volume: int = 75
_lock = threading.Lock()
_vendor_ffplay_path: Optional[str] = None
_vendor_download_lock = threading.Lock()


# ── ffplay resolution ─────────────────────────────────────────────────────────


def _loc_ffplay(name: str) -> Optional[Path]:
    exe = f"{name}.exe" if os.name == "nt" else name
    for sub in ("bin", "."):
        p = VENDOR_DIR / sub / exe
        if p.exists():
            return p
    return None


def _find_vendor_ffplay() -> Optional[str]:
    """ffplay under vendor/ffmpeg (direct bin/ or nested release folder)."""
    global _vendor_ffplay_path
    p = _loc_ffplay("ffplay")
    if p is None:
        for cand in VENDOR_DIR.rglob(
            "ffplay.exe" if os.name == "nt" else "ffplay"
        ):
            p = cand
            break
    if p is not None:
        _vendor_ffplay_path = str(p)
        return _vendor_ffplay_path
    return None


def _download_vendor_ffmpeg() -> str:
    """One-time download of the portable Windows ffmpeg build. Returns a status
    string; empty on success."""
    if os.name != "nt":
        return ("ffmpeg is not installed. Install it with your package "
                "manager (e.g. `brew install ffmpeg`) and try again.")
    with _vendor_download_lock:
        if _find_vendor_ffplay():
            return ""

        zip_path = VENDOR_DIR / "ffmpeg.zip"
        try:
            if not zip_path.exists():
                print(f"[Songs] ffplay not found — downloading a portable "
                      f"ffmpeg build (one time, ~150 MB)...")
                VENDOR_DIR.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(_VENDOR_ZIP_URL, timeout=300) as resp, \
                        open(zip_path, "wb") as out:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    last_log = 0.0
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last_log > 2.0 and total:
                            last_log = time.monotonic()
                            print(f"[Songs]   {done // (1024*1024)} / "
                                  f"{total // (1024*1024)} MB downloaded")

            # Extraction is idempotent and repeated here even when the zip was
            # already on disk, so a truncated download recovers on retry.
            print("[Songs] Extracting ffmpeg build...")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(VENDOR_DIR)
            # The zip is kept, not removed — the project's safety layer
            # forbids deletion on this drive, and re-runs never re-download
            # once the binaries exist.
        except Exception as e:
            return (f"Could not set up the bundled ffplay ({e}). If a partial "
                    f"'ffmpeg.zip' was left in {VENDOR_DIR}, remove that "
                    "folder by hand and try again — or install ffmpeg "
                    "manually so ffplay is on PATH.")

        found = _find_vendor_ffplay()
        if not found:
            return ("ffplay was not found after setup. Install ffmpeg "
                    "manually and make sure ffplay is on PATH.")
        print(f"[Songs] Using bundled ffplay: {found}")
        return ""


def _get_ffplay() -> tuple[Optional[str], str]:
    """Returns (ffplay_path_or_None, problem_text_if_none)."""
    p = shutil.which("ffplay")
    if p:
        return p, ""
    if VENDOR_DIR.exists():
        found = _find_vendor_ffplay()
        if found:
            return found, ""
    status = _download_vendor_ffmpeg()
    if status:
        return None, status
    found = _find_vendor_ffplay()
    if found:
        return found, ""
    return None, (
        "ffplay is not available and the automatic download was skipped. "
        "Install ffmpeg (which includes ffplay) and make sure it is on PATH."
    )


def _kill_proc() -> None:
    """Terminate any active playback process."""
    global _playback_proc, _is_paused
    if _playback_proc is not None:
        try:
            _playback_proc.kill()
            _playback_proc.wait(timeout=2)
        except Exception:
            pass
        _playback_proc = None
    _is_paused = False


# ── Search & download ──────────────────────────────────────────────────────────


def _search_and_download(query: str) -> tuple[Optional[Path], str, str, int]:
    """Search YouTube and download the best audio stream locally.

    Returns (file_path_or_None, title, error_text, duration_seconds).
    error_text is "" on success.
    """
    try:
        import yt_dlp
    except ImportError:
        return None, "", (
            "yt-dlp is not installed. Run:  "
            f'"{sys.executable if not getattr(sys, "frozen", False) else "python"}" '
            "-m pip install yt-dlp"
        ), 0

    search_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(search_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
        if not info or "entries" not in info or not info["entries"]:
            return None, "", f"Could not find any tracks for '{query}' on YouTube.", 0
        entry = info["entries"][0]
        title    = entry.get("title") or query
        ext      = entry.get("ext") or "m4a"
        vid_url  = entry.get("webpage_url") or entry.get("url")
        duration = int(entry.get("duration") or 0)
        if not vid_url:
            return None, "", f"Could not find a playable track for '{query}'.", 0

        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        target = MEDIA_DIR / f"song_{int(time.time() * 1000)}.{ext}"
        dl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(target),
            "retries": 3,
        }
        print(f"[Songs] Downloading '{title}'...")
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([vid_url])
        if not target.exists() or target.stat().st_size == 0:
            return None, title, f"Download of '{title}' failed — try again.", 0
        return target, title, "", duration
    except Exception as e:
        return None, query, f"Search/download failed: {e}", 0


# ── Playback ────────────────────────────────────────────────────────────────────


def _start_playback(file: Path, title: str) -> tuple[bool, str]:
    """Start ffplay on a local audio file, headless, in the background."""
    global _playback_proc, _current_track, _is_paused

    ffplay, problem = _get_ffplay()
    if not ffplay:
        print(f"[Songs] {problem}")
        return False, problem

    with _lock:
        _kill_proc()

        # ffplay has no -volume CLI flag; volume goes through the -af filter
        # graph. -autoexit makes it terminate when the track ends.
        cmd = [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-af", f"volume={_volume / 100:.2f}",
            str(file),
        ]

        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            _playback_proc = subprocess.Popen(cmd, **kwargs)
            _current_track = {
                "title": title,
                "file": str(file),
                "start_time": time.time(),
            }
            _is_paused = False
            return True, ""
        except Exception as e:
            print(f"[Songs] Failed to start ffplay: {e}")
            return False, f"Failed to start playback: {e}"


def _is_active() -> bool:
    """Check if audio is currently playing or paused."""
    global _playback_proc
    if _playback_proc is None:
        return False
    poll = _playback_proc.poll()
    return poll is None


# ── Action Handlers ────────────────────────────────────────────────────────────


def _do_play(query: Optional[str]) -> str:
    global _is_paused

    clean_q = (query or "").strip()
    if not clean_q:
        if _is_paused and _is_active():
            return _do_resume()
        clean_q = "top hit songs"

    # Clean up generic phrases like "koi gana", "any song", "gana sunao"
    for phrase in ("koi gana", "koi song", "any song", "a song", "some song",
                   "gana sunao", "song sunao", "gaana sunao"):
        if phrase in clean_q.lower():
            clean_q = re.sub(phrase, "top hits", clean_q, flags=re.IGNORECASE).strip()

    path, title, err, _duration = _search_and_download(clean_q)
    if err:
        return err
    if not path:
        return f"Could not find any playable tracks for '{clean_q}' on YouTube."

    ok, problem = _start_playback(path, title or clean_q)
    if ok:
        return f"Playing {title} on YouTube."
    return problem


def _do_pause() -> str:
    global _is_paused
    if not _is_active():
        return "No music is currently playing."
    if _is_paused:
        return "Music is already paused."

    try:
        import psutil
        p = psutil.Process(_playback_proc.pid)
        p.suspend()
        _is_paused = True
        return "Music paused."
    except ImportError:
        # psutil unavailable — stop the track instead of claiming a pause.
        return _do_stop()
    except Exception as e:
        return f"Could not pause music: {e}"


def _do_resume() -> str:
    global _is_paused
    if not _is_active():
        return "No music is currently paused or playing."
    if not _is_paused:
        return "Music is already playing."

    try:
        import psutil
        p = psutil.Process(_playback_proc.pid)
        p.resume()
        _is_paused = False
        title = _current_track.get("title", "track")
        return f"Resumed {title}."
    except Exception as e:
        return f"Could not resume music: {e}"


def _do_stop() -> str:
    global _current_track
    if not _is_active():
        return "No music is currently playing."

    with _lock:
        _kill_proc()
        _current_track = {}
    return "Music stopped."


def _do_current() -> str:
    if not _is_active():
        return "No music is currently playing."

    title = _current_track.get("title", "Unknown track")
    state = "paused" if _is_paused else "playing"
    return f"Currently {state}: {title}"


def _do_volume(vol: Optional[int]) -> str:
    global _volume
    if vol is None:
        return f"Current music volume is {_volume}%."

    if vol == -1:
        _volume = min(100, _volume + 15)
    elif vol == -2:
        _volume = max(0, _volume - 15)
    else:
        _volume = max(0, min(100, vol))

    # ffplay's volume filter is bound at start, so the new level applies to the
    # next track. (Restarting the current track just to change volume would
    # reset the playhead — not worth it.)
    return f"Music volume set to {_volume}%. It applies from the next song."


# ── Entrypoint ────────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatched by core/plugin_loader.py when the songs tool is called."""
    action = (parameters.get("action") or "play").strip().lower()
    query  = parameters.get("query")
    volume = parameters.get("volume")

    # Map aliases and search actions to play
    if action in (
        "play", "search", "search_song", "search_songs", "find",
        "find_song", "listen", "start", "stream", "song", "play_song"
    ):
        return _do_play(query)
    elif action in ("pause", "hold"):
        return _do_pause()
    elif action in ("resume", "unpause", "continue"):
        return _do_resume()
    elif action in ("stop", "kill", "end"):
        return _do_stop()
    elif action in ("next", "skip"):
        _do_stop()
        if query:
            return _do_play(query)
        return "Track stopped. Tell me what song to play next."
    elif action == "previous":
        return "Previous track is not supported on single stream playback."
    elif action in ("current", "now_playing", "whats_playing", "playing"):
        return _do_current()
    elif action in ("volume", "set_volume"):
        return _do_volume(volume)
    elif query:
        # If action is unknown but a song query was provided, play it
        return _do_play(query)
    else:
        return f"Unknown action: '{action}'. Supported actions: play, search, pause, resume, stop, current, volume."
