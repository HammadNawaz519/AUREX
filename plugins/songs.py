"""
AUREX Songs Plugin — Full-Track Music Playback via YouTube
===========================================================
Plays full songs directly and completely free using yt-dlp stream extraction
and ffplay. No Spotify account or API keys required. Works 100% locally.

Supported Actions:
  - play <song name>
  - pause music / resume music / stop music
  - current song / what's playing
  - volume <0-100>, volume up, volume down
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from typing import Optional

# ── Plugin metadata ───────────────────────────────────────────────────────────

PLUGIN = {
    "name": "songs",
    "description": (
        "Plays full songs and controls music playback for the user via YouTube. "
        "Use this tool when the user says 'play [song name]', "
        "'play [song] by [artist]', 'pause music', 'resume music', "
        "'stop music', 'next song', 'skip', 'previous song', "
        "'what\\'s playing', 'current song', 'set volume to [number]', "
        "'volume up', or 'volume down'. "
        "This plugin streams and plays full tracks locally without any account "
        "or API keys needed. "
        "Do NOT use web_search or open_browser to play music — always use "
        "this plugin instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: play, pause, resume, stop, next, previous, "
                    "current, volume"
                ),
            },
            "query": {
                "type": "STRING",
                "description": (
                    "Song name (and optionally artist) to search for "
                    "(required for action=play)."
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

# ── Global Playback State ──────────────────────────────────────────────────────

_playback_proc: Optional[subprocess.Popen] = None
_current_track: dict = {}
_is_paused: bool = False
_volume: int = 75
_lock = threading.Lock()


def _get_ffplay() -> Optional[str]:
    """Find the path to ffplay on the system."""
    return shutil.which("ffplay")


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


def _search_and_extract(query: str) -> Optional[dict]:
    """Search YouTube and extract the best audio stream URL using yt-dlp."""
    try:
        import yt_dlp

        ydl_opts = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1",
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if not info or "entries" not in info or not info["entries"]:
                return None
            entry = info["entries"][0]
            return {
                "title": entry.get("title", query),
                "url": entry.get("url"),
                "duration": entry.get("duration", 0),
                "uploader": entry.get("uploader", "YouTube"),
                "webpage_url": entry.get("webpage_url", ""),
            }
    except Exception as e:
        print(f"[Songs] yt-dlp search error: {e}")
        return None


def _start_playback(stream_url: str, title: str, duration: int = 0) -> bool:
    """Start ffplay in background without a window."""
    global _playback_proc, _current_track, _is_paused

    ffplay = _get_ffplay()
    if not ffplay:
        print("[Songs] ffplay executable not found.")
        return False

    with _lock:
        _kill_proc()

        cmd = [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-volume", str(_volume),
            stream_url,
        ]

        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            _playback_proc = subprocess.Popen(cmd, **kwargs)
            _current_track = {
                "title": title,
                "duration": duration,
                "start_time": time.time(),
            }
            _is_paused = False
            return True
        except Exception as e:
            print(f"[Songs] Failed to start ffplay: {e}")
            return False


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

    if not query or not query.strip():
        if _is_paused and _is_active():
            return _do_resume()
        return "Please specify what song you'd like to play."

    track = _search_and_extract(query.strip())
    if not track or not track.get("url"):
        return f"Could not find any playable tracks for '{query}' on YouTube."

    success = _start_playback(track["url"], track["title"], track.get("duration", 0))
    if success:
        return f"Playing {track['title']} on YouTube."
    return f"Failed to start playback for '{track['title']}'."


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

    # If already playing, restart current stream with new volume
    # Or inform the user the next song will play at this level
    return f"Music volume set to {_volume}%."


# ── Entrypoint ────────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatched by core/plugin_loader.py when the songs tool is called."""
    action = (parameters.get("action") or "play").strip().lower()
    query  = parameters.get("query")
    volume = parameters.get("volume")

    if action == "play":
        return _do_play(query)
    elif action == "pause":
        return _do_pause()
    elif action == "resume":
        return _do_resume()
    elif action in ("stop", "kill"):
        return _do_stop()
    elif action in ("next", "skip"):
        _do_stop()
        if query:
            return _do_play(query)
        return "Track stopped. Tell me what song to play next."
    elif action == "previous":
        return "Previous track is not supported on single stream playback."
    elif action in ("current", "now_playing", "whats_playing"):
        return _do_current()
    elif action == "volume":
        return _do_volume(volume)
    else:
        return f"Unknown action: '{action}'. Supported actions: play, pause, resume, stop, current, volume."
