"""
AUREX Songs Plugin -- Apple iTunes Search API + Deezer API/CDN
Plays music instantly on voice command. Zero blocking -- streams previews
from Deezer CDN (30-second HQ previews) with iTunes as the search backbone.

Trigger phrases:
  "play [song]", "play [song] by [artist]", "play some [genre]"
  "stop music", "pause music", "skip song", "next song"

No extra files -- all logic lives here.
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.parse
import urllib.request
from typing import Optional

PLUGIN = {
    "name": "songs",
    "description": (
        "Plays music instantly when the user says 'play [song name]', "
        "'play [song] by [artist]', 'play some [genre] music', 'stop music', "
        "'pause song', 'next song', or 'skip'. "
        "Uses iTunes Search + Deezer CDN for zero-latency 30-second previews. "
        "Do NOT use the web_search or open_browser tools for playing music -- "
        "always use this plugin instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "One of: play, stop, pause, resume, next",
            },
            "query": {
                "type": "STRING",
                "description": "Song name, artist, or genre to search for (for action=play)",
            },
        },
        "required": ["action"],
    },
}

_lock = threading.Lock()
_play_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_pause_event = threading.Event()
_current_track: Optional[dict] = None
_SD_AVAILABLE: Optional[bool] = None


def _sounddevice_ok() -> bool:
    global _SD_AVAILABLE
    if _SD_AVAILABLE is None:
        try:
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401
            _SD_AVAILABLE = True
        except Exception:
            _SD_AVAILABLE = False
    return bool(_SD_AVAILABLE)


_ITUNES_BASE = "https://itunes.apple.com/search"
_DEEZER_SEARCH = "https://api.deezer.com/search"
_UA = "AUREX/1.0"


def _http_get(url: str, timeout: int = 6) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _itunes_search(query: str, limit: int = 5) -> list:
    params = urllib.parse.urlencode(
        {"term": query, "media": "music", "entity": "song", "limit": limit, "country": "US"}
    )
    try:
        data = json.loads(_http_get(f"{_ITUNES_BASE}?{params}"))
        results = []
        for item in data.get("results", []):
            prev = item.get("previewUrl", "")
            if prev:
                results.append(
                    {
                        "title": item.get("trackName", "Unknown"),
                        "artist": item.get("artistName", "Unknown"),
                        "preview_url": prev,
                        "source": "iTunes",
                    }
                )
        return results
    except Exception:
        return []


def _deezer_search(query: str, limit: int = 5) -> list:
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    try:
        data = json.loads(_http_get(f"{_DEEZER_SEARCH}?{params}"))
        results = []
        for item in data.get("data", []):
            prev = item.get("preview", "")
            if prev:
                results.append(
                    {
                        "title": item.get("title", "Unknown"),
                        "artist": item.get("artist", {}).get("name", "Unknown"),
                        "preview_url": prev,
                        "source": "Deezer",
                    }
                )
        return results
    except Exception:
        return []


def _search(query: str) -> list:
    results = _deezer_search(query)
    if not results:
        results = _itunes_search(query)
    return results


def _stream_mp3(url: str, stop: threading.Event, pause: threading.Event) -> None:
    try:
        import sounddevice as sd
        import numpy as np
        import io
        import time

        try:
            from pydub import AudioSegment  # type: ignore

            data = _http_get(url, timeout=10)
            seg = AudioSegment.from_mp3(io.BytesIO(data))
            arr = np.array(seg.get_array_of_samples(), dtype=np.float32)
            arr /= float(1 << (8 * seg.sample_width - 1))
            if seg.channels == 2:
                arr = arr.reshape(-1, 2)
            else:
                arr = arr.reshape(-1, 1)
            samplerate = seg.frame_rate
            CHUNK = 2048
            for i in range(0, len(arr), CHUNK):
                if stop.is_set():
                    return
                while pause.is_set() and not stop.is_set():
                    time.sleep(0.05)
                sd.play(arr[i : i + CHUNK], samplerate=samplerate, blocking=True)
        except ImportError:
            import shutil, subprocess

            if shutil.which("ffmpeg"):
                proc = subprocess.Popen(
                    ["ffmpeg", "-i", url, "-f", "f32le", "-ar", "44100", "-ac", "2", "-"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                CHUNK = 4096
                while not stop.is_set():
                    while pause.is_set() and not stop.is_set():
                        time.sleep(0.05)
                    raw = proc.stdout.read(CHUNK * 2 * 4)
                    if not raw:
                        break
                    chunk = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
                    sd.play(chunk, samplerate=44100, blocking=True)
                proc.terminate()
            else:
                raw = _http_get(url, timeout=15)
                arr = np.frombuffer(raw[44:], dtype=np.int16).astype(np.float32) / 32768.0
                arr = arr.reshape(-1, 2) if len(arr) % 2 == 0 else arr.reshape(-1, 1)
                sd.play(arr, samplerate=44100, blocking=False)
                while sd.get_stream().active:
                    if stop.is_set():
                        sd.stop()
                        return
                    while pause.is_set() and not stop.is_set():
                        time.sleep(0.05)
                    time.sleep(0.1)
    except Exception as exc:
        print(f"[Songs] Playback error: {exc}")


def _play_track(track: dict) -> None:
    global _current_track
    _stop_event.clear()
    _pause_event.clear()
    with _lock:
        _current_track = track
    _stream_mp3(track["preview_url"], _stop_event, _pause_event)
    with _lock:
        _current_track = None


def _start_playback(track: dict) -> None:
    global _play_thread
    _stop_event.set()
    if _play_thread and _play_thread.is_alive():
        _play_thread.join(timeout=1.0)
    _play_thread = threading.Thread(
        target=_play_track, args=(track,), daemon=True, name="songs-playback"
    )
    _play_thread.start()


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "play").lower().strip()
    query = (parameters.get("query") or "").strip()

    def _log(msg: str):
        if player:
            try:
                player.write_log(f"SONGS: {msg}")
            except Exception:
                pass

    if action == "stop":
        _stop_event.set()
        _pause_event.clear()
        msg = "Music stopped."
        _log(msg)
        return msg

    if action == "pause":
        _pause_event.set()
        msg = "Music paused."
        _log(msg)
        return msg

    if action in ("resume", "unpause"):
        _pause_event.clear()
        msg = "Resuming music."
        _log(msg)
        return msg

    if action in ("next", "skip"):
        _stop_event.set()
        msg = "Skipping track."
        _log(msg)
        return msg

    if not query:
        return "Sir, please tell me what song or artist to play."

    if not _sounddevice_ok():
        return "Sir, audio playback unavailable. Run: pip install sounddevice numpy"

    result_holder: list = []
    error_holder: list = []
    ready = threading.Event()

    def _search_and_play():
        try:
            tracks = _search(query)
            if not tracks:
                error_holder.append(f"No preview found for '{query}'.")
                return
            track = tracks[0]
            result_holder.append(track)
            _start_playback(track)
        except Exception as exc:
            error_holder.append(str(exc))
        finally:
            ready.set()

    threading.Thread(target=_search_and_play, daemon=True, name="songs-search").start()
    ready.wait(timeout=8.0)

    if error_holder:
        msg = f"Sir, songs plugin error: {error_holder[0]}"
        _log(f"ERROR -- {error_holder[0]}")
        return msg

    if not result_holder:
        msg = f"Sir, I could not find a playable preview for '{query}'."
        _log(f"No result for '{query}'")
        return msg

    track = result_holder[0]
    msg = f"Playing \"{track['title']}\" by {track['artist']} [{track['source']}]."
    _log(msg)
    return msg
