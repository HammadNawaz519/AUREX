"""
AUREX Spotify Plugin — Full-Track Spotify Playback via Spotify Connect
======================================================================

Uses Spotify Authorization Code with PKCE (no client secret required for
PKCE flows). Tokens are stored in config/api_keys.json under the
plugin_config["spotify"] namespace via AUREX's built-in config manager.

OAuth Callback: The AUREX dashboard server (port 8000) hosts
  GET /spotify/callback?code=...&state=...
The plugin registers that route on import by calling
_register_callback_route() — if the dashboard isn't available the auth
flow falls back to a manual localhost redirect server on port 8765.

Requires:
  pip install requests
  (No extra audio library needed — Spotify handles all audio.)

Environment / PLUGIN SETTINGS:
  SPOTIFY_CLIENT_ID    — your Spotify Developer App client ID
  (No client secret is needed for PKCE.)
  SPOTIFY_REDIRECT_URI — defaults to http://127.0.0.1:8765/callback
                         (Change to your dashboard URL if preferred.)

Trigger phrases (Gemini decides):
  "play <song>", "play <song> by <artist>"
  "pause music", "resume music", "stop music"
  "next song", "skip", "previous song"
  "what's playing", "current song"
  "set volume to 50", "volume up", "volume down"
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

# ── Plugin metadata ───────────────────────────────────────────────────────────

PLUGIN = {
    "name": "spotify",
    "description": (
        "Controls Spotify music playback for the user. "
        "Use this tool when the user says 'play [song name]', "
        "'play [song] by [artist]', 'pause music', 'resume music', "
        "'stop music', 'next song', 'skip', 'previous song', "
        "'what\\'s playing', 'current song', 'set volume to [number]', "
        "'volume up', or 'volume down'. "
        "This plugin plays FULL tracks through the user\\'s Spotify account "
        "on whatever Spotify device they have open. "
        "Do NOT use web_search or open_browser to play music — always use "
        "this plugin instead. "
        "Requires Spotify Premium for playback control."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: play, pause, resume, stop, next, previous, "
                    "current, volume, connect"
                ),
            },
            "query": {
                "type": "STRING",
                "description": (
                    "Song name (and optionally artist) to search for "
                    "(only for action=play)."
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
    # Non-blocking so AUREX doesn't freeze while the API call is in flight.
    "behavior": "NON_BLOCKING",
}

# Shown in the Plugin Settings UI so the user can enter their Client ID.
PLUGIN_SETTINGS = {
    "namespace": "spotify",
    "title": "Spotify",
    "fields": [
        {
            "key": "client_id",
            "label": "Spotify Client ID",
            "type": "text",
            "placeholder": "Your Spotify Developer App Client ID",
            "secret": False,
        },
        {
            "key": "client_secret",
            "label": "Spotify Client Secret",
            "type": "text",
            "placeholder": "Your Spotify App Client Secret",
            "secret": True,
        },
        {
            "key": "redirect_uri",
            "label": "Redirect URI",
            "type": "text",
            "placeholder": "http://127.0.0.1:8765/callback",
            "secret": False,
        },
    ],
    "action": {
        "label": "Connect Spotify",
        "callback": "spotify_connect",   # matched by plugin name + action key
    },
}

# ── Constants ─────────────────────────────────────────────────────────────────

_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "streaming",
])

_AUTH_URL   = "https://accounts.spotify.com/authorize"
_TOKEN_URL  = "https://accounts.spotify.com/api/token"
_API_BASE   = "https://api.spotify.com/v1"

_FALLBACK_PORT = 8765   # used only when the dashboard callback route is unavailable

# ── Config helpers ────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        return get_plugin_config("spotify")
    except Exception:
        return {}


def _save(**kw) -> None:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config("spotify", kw)
    except Exception as e:
        print(f"[Spotify] Config save error: {e}")


def _client_id() -> Optional[str]:
    return (
        os.environ.get("SPOTIFY_CLIENT_ID")
        or _cfg().get("client_id")
        or ""
    ).strip() or None


def _client_secret() -> Optional[str]:
    return (
        os.environ.get("SPOTIFY_CLIENT_SECRET")
        or _cfg().get("client_secret")
        or ""
    ).strip() or None


def _redirect_uri() -> str:
    return (
        os.environ.get("SPOTIFY_REDIRECT_URI")
        or _cfg().get("redirect_uri")
        or f"http://127.0.0.1:{_FALLBACK_PORT}/callback"
    ).strip()


# ── PKCE helpers ──────────────────────────────────────────────────────────────

def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── Token storage ─────────────────────────────────────────────────────────────
# All tokens live in config/api_keys.json under plugin_config["spotify"].
# The access_token + expires_at are refreshed automatically.

_token_lock = threading.Lock()


def _load_tokens() -> dict:
    c = _cfg()
    return {
        "access_token":  c.get("access_token", ""),
        "refresh_token": c.get("refresh_token", ""),
        "expires_at":    float(c.get("expires_at", 0)),
    }


def _store_tokens(access_token: str, refresh_token: Optional[str],
                  expires_in: int) -> None:
    kw: dict = {
        "access_token": access_token,
        "expires_at":   time.time() + expires_in - 30,  # 30 s safety margin
    }
    if refresh_token:
        kw["refresh_token"] = refresh_token
    _save(**kw)


def _get_valid_token() -> Optional[str]:
    """Return a valid access token, refreshing if needed. None = not authorised."""
    with _token_lock:
        toks = _load_tokens()
        if not toks["access_token"]:
            return None

        if time.time() < toks["expires_at"]:
            return toks["access_token"]

        # ── Token expired — try to refresh ──────────────────────────────
        rt = toks.get("refresh_token")
        if not rt:
            return None

        cid = _client_id()
        if not cid:
            return None

        try:
            req_params = {
                "grant_type":    "refresh_token",
                "refresh_token": rt,
                "client_id":     cid,
            }
            sec = _client_secret()
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if sec:
                req_params["client_secret"] = sec
                auth_str = base64.b64encode(f"{cid}:{sec}".encode("ascii")).decode("ascii")
                headers["Authorization"] = f"Basic {auth_str}"
            body = urllib.parse.urlencode(req_params).encode()
            req = urllib.request.Request(
                _TOKEN_URL, data=body,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())

            new_access  = data.get("access_token", "")
            new_refresh = data.get("refresh_token") or rt  # Spotify may rotate it
            expires_in  = int(data.get("expires_in", 3600))
            if not new_access:
                raise ValueError("Empty access_token in refresh response")
            _store_tokens(new_access, new_refresh, expires_in)
            return new_access

        except Exception as e:
            print(f"[Spotify] Token refresh failed: {e}")
            return None


# ── Spotify API client ────────────────────────────────────────────────────────

def _api(method: str, path: str, body: Optional[dict] = None,
         params: Optional[dict] = None) -> tuple[int, dict]:
    """
    Make a Spotify API call. Returns (status_code, response_dict).
    Never raises — always returns something the caller can inspect.
    """
    token = _get_valid_token()
    if not token:
        return 401, {"error": "not_authorized"}

    url = f"{_API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
            raw = r.read()
            return status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read()
            return status, json.loads(raw) if raw.strip() else {}
        except Exception:
            return status, {}
    except Exception as e:
        print(f"[Spotify] Network error: {e}")
        return 0, {"error": str(e)}


def _search(query: str, search_type: str = "track", limit: int = 5) -> dict:
    status, data = _api("GET", "/search", params={
        "q": query, "type": search_type, "limit": limit, "market": "US"
    })
    if status == 200:
        return data
    return {}


def _get_devices() -> list[dict]:
    status, data = _api("GET", "/me/player/devices")
    if status == 200:
        return data.get("devices", [])
    return []


def _get_current_playback() -> dict:
    status, data = _api("GET", "/me/player")
    if status == 200:
        return data
    return {}


def _start_playback(uris: list[str], device_id: Optional[str] = None) -> int:
    params = {"device_id": device_id} if device_id else None
    status, _ = _api("PUT", "/me/player/play",
                     body={"uris": uris}, params=params)
    return status


def _pause_playback(device_id: Optional[str] = None) -> int:
    params = {"device_id": device_id} if device_id else None
    status, _ = _api("PUT", "/me/player/pause", params=params)
    return status


def _resume_playback(device_id: Optional[str] = None) -> int:
    params = {"device_id": device_id} if device_id else None
    status, _ = _api("PUT", "/me/player/play", params=params)
    return status


def _next_track(device_id: Optional[str] = None) -> int:
    params = {"device_id": device_id} if device_id else None
    status, _ = _api("POST", "/me/player/next", params=params)
    return status


def _previous_track(device_id: Optional[str] = None) -> int:
    params = {"device_id": device_id} if device_id else None
    status, _ = _api("POST", "/me/player/previous", params=params)
    return status


def _set_volume(volume_percent: int, device_id: Optional[str] = None) -> int:
    params: dict = {"volume_percent": max(0, min(100, volume_percent))}
    if device_id:
        params["device_id"] = device_id
    status, _ = _api("PUT", "/me/player/volume", params=params)
    return status


def _transfer_playback(device_id: str, play: bool = True) -> int:
    status, _ = _api("PUT", "/me/player",
                     body={"device_ids": [device_id], "play": play})
    return status


# ── Device resolution ─────────────────────────────────────────────────────────

def _best_device() -> tuple[Optional[str], str]:
    """
    Returns (device_id_or_None, description).
    Prefers the currently active device; falls back to any available device.
    """
    devices = _get_devices()
    if not devices:
        return None, "no_devices"

    # Prefer active
    for d in devices:
        if d.get("is_active"):
            return d["id"], d.get("name", "active device")

    # Prefer non-restricted
    for d in devices:
        if not d.get("is_restricted", True):
            return d["id"], d.get("name", "available device")

    # Last resort: any device
    d = devices[0]
    return d["id"], d.get("name", "Spotify device")


# ── Status code interpretation ────────────────────────────────────────────────

def _interpret(status: int, context: str = "") -> Optional[str]:
    """Return a user-friendly error string, or None if the call succeeded."""
    if status in (200, 201, 202, 204, 0):
        return None   # 204 No Content is success for many Spotify endpoints
    if status == 401:
        return "Spotify authorization has expired. Say 'connect Spotify' to reconnect."
    if status == 403:
        return ("Spotify playback requires Spotify Premium. "
                "Please upgrade your Spotify account.")
    if status == 404:
        return "No active Spotify device found. Open Spotify on a device and try again."
    if status == 429:
        return "Spotify is rate-limiting requests. Please wait a moment and try again."
    if status >= 500:
        return "Spotify's servers returned an error. Please try again."
    return f"Spotify returned status {status}{' (' + context + ')' if context else ''}."


# ── OAuth PKCE flow ───────────────────────────────────────────────────────────

# In-memory state for the pending auth flow (verifier + state nonce).
_pending_verifier: Optional[str] = None
_pending_state:    Optional[str] = None
_auth_event = threading.Event()
_auth_result: Optional[str] = None   # "ok" | error message


def _build_auth_url() -> Optional[str]:
    """Build the Spotify authorization URL. Returns None if Client ID is missing."""
    global _pending_verifier, _pending_state

    cid = _client_id()
    if not cid:
        return None

    verifier = _pkce_verifier()
    challenge = _pkce_challenge(verifier)
    state = secrets.token_urlsafe(16)

    _pending_verifier = verifier
    _pending_state    = state

    params = {
        "client_id":             cid,
        "response_type":         "code",
        "redirect_uri":          _redirect_uri(),
        "code_challenge_method": "S256",
        "code_challenge":        challenge,
        "state":                 state,
        "scope":                 _SCOPES,
    }
    return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


def handle_spotify_callback(code: str, state: str) -> str:
    """
    Called by the dashboard server's /spotify/callback route (or the fallback
    localhost server) once Spotify redirects back with an authorization code.
    Returns a human-readable result string.
    """
    global _auth_result

    if state != _pending_state:
        msg = "State mismatch — possible CSRF. Please try connecting Spotify again."
        _auth_result = msg
        _auth_event.set()
        return msg

    cid      = _client_id()
    verifier = _pending_verifier
    ruri     = _redirect_uri()

    if not cid or not verifier:
        msg = "Auth flow state lost. Please try connecting Spotify again."
        _auth_result = msg
        _auth_event.set()
        return msg

    try:
        req_params = {
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  ruri,
            "client_id":     cid,
            "code_verifier": verifier,
        }
        sec = _client_secret()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if sec:
            req_params["client_secret"] = sec
            auth_str = base64.b64encode(f"{cid}:{sec}".encode("ascii")).decode("ascii")
            headers["Authorization"] = f"Basic {auth_str}"
        body = urllib.parse.urlencode(req_params).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        access_token  = data.get("access_token", "")
        refresh_token = data.get("refresh_token", "")
        expires_in    = int(data.get("expires_in", 3600))

        if not access_token:
            raise ValueError(f"No access_token in response: {data}")

        _store_tokens(access_token, refresh_token, expires_in)
        _auth_result = "ok"
        _auth_event.set()
        return "Spotify connected successfully!"

    except Exception as e:
        msg = f"Token exchange failed: {e}"
        print(f"[Spotify] {msg}")
        _auth_result = msg
        _auth_event.set()
        return msg


# ── Dashboard callback route registration ─────────────────────────────────────

_callback_registered = False


def _register_callback_route() -> bool:
    """
    Inject GET /spotify/callback into the running FastAPI app.
    This works because dashboard/server.py exposes DashboardServer.app
    which is wired into main.py via the same module reference.
    Returns True if successful.
    """
    global _callback_registered
    if _callback_registered:
        return True
    try:
        # Walk sys.modules to find the live DashboardServer instance's app
        import sys
        ds_mod = sys.modules.get("dashboard.server")
        if ds_mod is None:
            return False

        # The module-level DashboardServer is created once; find it
        ds_instance = getattr(ds_mod, "_dashboard_instance", None)
        if ds_instance is None:
            # Try to find it through any attribute that is a DashboardServer
            for attr in dir(ds_mod):
                obj = getattr(ds_mod, attr, None)
                if obj.__class__.__name__ == "DashboardServer":
                    ds_instance = obj
                    break
        if ds_instance is None:
            return False

        fast_app = getattr(ds_instance, "app", None)
        if fast_app is None:
            return False

        from fastapi.responses import HTMLResponse

        @fast_app.get("/spotify/callback", response_class=HTMLResponse)
        async def spotify_callback_ep(code: str = "", state: str = "",
                                      error: str = ""):
            if error:
                msg = f"Spotify authorization denied: {error}"
                handle_spotify_callback.__globals__["_auth_result"] = msg
                _auth_event.set()
                return HTMLResponse(
                    _callback_page("❌ Authorization denied",
                                   "Spotify authorization was denied. "
                                   "Please try again.", success=False)
                )
            if not code:
                return HTMLResponse(
                    _callback_page("❌ Missing code",
                                   "No authorization code received.", success=False)
                )
            result = handle_spotify_callback(code, state)
            success = (result == "Spotify connected successfully!")
            return HTMLResponse(
                _callback_page(
                    "✅ Spotify Connected!" if success else "❌ Connection failed",
                    result if success else f"Error: {result}",
                    success=success,
                )
            )

        _callback_registered = True
        print("[Spotify] /spotify/callback route registered on dashboard.")
        return True

    except Exception as e:
        print(f"[Spotify] Could not register dashboard callback route: {e}")
        return False


def _callback_page(title: str, message: str, success: bool = True) -> str:
    color = "#1DB954" if success else "#f87171"
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  body{{background:#121212;color:#eee;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;
       height:100vh;margin:0;text-align:center}}
  h1{{color:{color};font-size:1.6rem}}
  p{{color:#999;font-size:1rem;max-width:400px}}
</style></head>
<body><div>
  <h1>{title}</h1>
  <p>{message}</p>
  <p style="color:#555;font-size:.85rem">You can close this tab.</p>
</div></body></html>"""


# ── Fallback local redirect server ────────────────────────────────────────────

def _start_fallback_server() -> None:
    """
    Start a one-shot HTTP server on localhost:8765 to catch Spotify's redirect
    when the dashboard callback route isn't available.
    """
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            code  = qs.get("code",  [""])[0]
            state = qs.get("state", [""])[0]
            error = qs.get("error", [""])[0]

            if error:
                result = f"Spotify authorization denied: {error}"
                _auth_event.set()
            elif code:
                result = handle_spotify_callback(code, state)
            else:
                result = "No code received."
                _auth_event.set()

            success = (result == "Spotify connected successfully!")
            body = _callback_page(
                "✅ Spotify Connected!" if success else "❌ Error",
                result, success=success,
            ).encode()

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass   # silence HTTP request logs

    try:
        server = http.server.HTTPServer(("127.0.0.1", _FALLBACK_PORT), _Handler)
        server.timeout = 180   # wait up to 3 minutes for the redirect
        server.handle_request()
        server.server_close()
    except Exception as e:
        print(f"[Spotify] Fallback redirect server error: {e}")
        _auth_event.set()


# ── Connect action ────────────────────────────────────────────────────────────

def _connect_spotify() -> str:
    """
    Start the Spotify PKCE auth flow. Opens the user's browser. Returns a
    string that is spoken back to the user.
    """
    global _auth_event, _auth_result

    cid = _client_id()
    if not cid:
        return (
            "Spotify Client ID is not configured. "
            "Please open Plugin Settings and enter your Spotify Client ID, "
            "then say 'connect Spotify' again."
        )

    url = _build_auth_url()
    if not url:
        return "Could not build the Spotify authorization URL."

    # Prefer dashboard callback route; fall back to local server
    use_dashboard = _register_callback_route()

    if not use_dashboard:
        # Start fallback local server in a daemon thread
        threading.Thread(target=_start_fallback_server,
                         daemon=True, name="spotify-auth-server").start()

    _auth_event.clear()
    _auth_result = None

    webbrowser.open(url)
    print(f"[Spotify] Opening browser for authorization…")

    return (
        "I've opened the Spotify login page in your browser. "
        "Please log in and grant access. I'll confirm once you're connected."
    )


# ── Play action ───────────────────────────────────────────────────────────────

def _play(query: str) -> str:
    if not query.strip():
        return "Please tell me what song or artist to play on Spotify."

    token = _get_valid_token()
    if not token:
        return (
            "Spotify isn't connected yet. "
            "Say 'connect Spotify' to link your account."
        )

    # ── Search ────────────────────────────────────────────────────────────────
    data = _search(query, "track", 5)
    tracks = data.get("tracks", {}).get("items", [])
    if not tracks:
        return f"I couldn't find \"{query}\" on Spotify."

    # Score: exact name+artist match first, then substring, then first result
    ql = query.lower()
    best = None
    for t in tracks:
        name    = t.get("name", "").lower()
        artists = " ".join(a.get("name", "") for a in t.get("artists", [])).lower()
        if name in ql or ql in name or artists in ql:
            best = t
            break
    if best is None:
        best = tracks[0]

    track_name   = best.get("name", "Unknown")
    artist_names = ", ".join(a.get("name", "") for a in best.get("artists", []))
    uri          = best.get("uri", "")

    if not uri:
        return "I found the song but couldn't get its Spotify URI."

    # ── Resolve device ────────────────────────────────────────────────────────
    device_id, device_name = _best_device()
    if device_id is None:
        return (
            f"I found \"{track_name}\" by {artist_names}, but there is no "
            "active Spotify device. Please open Spotify on your phone, "
            "computer, or speaker and try again."
        )

    # If the device isn't already active, transfer playback to it first
    playback = _get_current_playback()
    current_device = (playback.get("device") or {}).get("id")
    if current_device and current_device != device_id:
        _transfer_playback(device_id, play=False)
        time.sleep(0.3)

    # ── Start playback ────────────────────────────────────────────────────────
    status = _start_playback([uri], device_id)
    err = _interpret(status, "start_playback")
    if err:
        return err

    return f'Playing "{track_name}" by {artist_names} on Spotify.'


# ── main run() ────────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    action = (parameters.get("action") or "play").lower().strip()
    query  = (parameters.get("query")  or "").strip()
    vol    = parameters.get("volume")

    def _log(msg: str):
        if player:
            try:
                player.write_log(f"SPOTIFY: {msg}")
            except Exception:
                pass

    # ── Connect ───────────────────────────────────────────────────────────────
    if action == "connect":
        result = _connect_spotify()
        _log(result)
        return result

    # ── Play ──────────────────────────────────────────────────────────────────
    if action == "play":
        result = _play(query)
        _log(result)
        return result

    # ── For all control actions, check auth first ─────────────────────────────
    token = _get_valid_token()
    if not token:
        return (
            "Spotify isn't connected. "
            "Say 'connect Spotify' to link your account first."
        )

    device_id, _ = _best_device()

    # ── Pause ─────────────────────────────────────────────────────────────────
    if action == "pause":
        status = _pause_playback(device_id)
        err = _interpret(status, "pause")
        result = err or "Music paused."
        _log(result)
        return result

    # ── Resume / Unpause ──────────────────────────────────────────────────────
    if action in ("resume", "unpause", "stop"):
        # Spotify has no separate "stop" — resume/pause is the toggle.
        # If the user says "stop" we pause.
        if action == "stop":
            status = _pause_playback(device_id)
            err = _interpret(status, "stop")
            result = err or "Music stopped."
        else:
            status = _resume_playback(device_id)
            err = _interpret(status, "resume")
            result = err or "Resuming music."
        _log(result)
        return result

    # ── Next / Skip ───────────────────────────────────────────────────────────
    if action in ("next", "skip"):
        status = _next_track(device_id)
        err = _interpret(status, "next")
        result = err or "Skipped to next track."
        _log(result)
        return result

    # ── Previous ──────────────────────────────────────────────────────────────
    if action == "previous":
        status = _previous_track(device_id)
        err = _interpret(status, "previous")
        result = err or "Going back to the previous track."
        _log(result)
        return result

    # ── Current track ─────────────────────────────────────────────────────────
    if action in ("current", "now_playing", "what_playing"):
        pb = _get_current_playback()
        item = pb.get("item")
        if not item or not pb.get("is_playing"):
            result = "Nothing is currently playing on Spotify."
        else:
            name    = item.get("name", "Unknown")
            artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
            result  = f'Currently playing "{name}" by {artists}.'
        _log(result)
        return result

    # ── Volume ────────────────────────────────────────────────────────────────
    if action == "volume":
        try:
            target_vol = int(vol) if vol is not None else 50
        except (TypeError, ValueError):
            target_vol = 50

        if target_vol == -1:
            # Volume up: get current and add 10
            pb = _get_current_playback()
            cur = (pb.get("device") or {}).get("volume_percent") or 50
            target_vol = min(100, int(cur) + 10)
        elif target_vol == -2:
            # Volume down
            pb = _get_current_playback()
            cur = (pb.get("device") or {}).get("volume_percent") or 50
            target_vol = max(0, int(cur) - 10)

        target_vol = max(0, min(100, target_vol))
        status = _set_volume(target_vol, device_id)
        err = _interpret(status, "volume")
        result = err or f"Spotify volume set to {target_vol}%."
        _log(result)
        return result

    return f"I don't recognise the Spotify action '{action}'."


# ── Register callback route on import ─────────────────────────────────────────
# Attempt immediately; if the dashboard isn't ready yet this is a no-op
# and will be retried the first time _connect_spotify() is called.
try:
    _register_callback_route()
except Exception:
    pass
