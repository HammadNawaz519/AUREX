"""
AUREX GMAIL PLUGIN
==================
Autonomous Intelligent Email Dispatcher for AUREX AI Assistant.
Generates stunning, responsive, high-end HTML UI emails with customizable themes.

Drop-in plugin discovered automatically by core.plugin_loader.
"""

from __future__ import annotations

import os
import sys
import json
import re
import ssl
import smtplib
import threading
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate, make_msgid

# Force UTF-8 on Windows consoles
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure repo root is available in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from memory.config_manager import get_plugin_setting, get_plugin_config


# ── CONFIGURATION & CREDENTIALS ───────────────────────────────────────────────
DEFAULT_GMAIL_USER = "hammadnawaz519@gmail.com"
DEFAULT_GMAIL_APP_PASSWORD = "rpyu qgwy pbed bldh"
DEFAULT_SENDER_NAME = "Hammad Nawaz (via AUREX)"

CONFIG_DIR = _ROOT / "config"
MEMORY_DIR = _ROOT / "memory"
SENT_EMAILS_PATH = MEMORY_DIR / "sent_emails.json"
_SENT_LOCK = threading.Lock()

CONTACTS_PATH = CONFIG_DIR / "contacts.json"
API_KEYS_PATH = CONFIG_DIR / "api_keys.json"
ENV_PATH = _ROOT / ".env"


def _load_env_vars() -> dict:
    env_vars = {}
    if ENV_PATH.exists():
        try:
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env_vars[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            pass
    return env_vars


def get_credentials() -> tuple[str, str, str]:
    """Retrieves (user_email, app_password, sender_name)."""
    # 1. Check plugin settings (plugin_config.gmail)
    cfg_user = get_plugin_setting("gmail", "user")
    cfg_pwd = get_plugin_setting("gmail", "app_password")
    cfg_name = get_plugin_setting("gmail", "sender_name")

    # 2. Check .env
    env = _load_env_vars()
    user = cfg_user or os.environ.get("GMAIL_USER") or env.get("GMAIL_USER")
    pwd = cfg_pwd or os.environ.get("GMAIL_APP_PASSWORD") or env.get("GMAIL_APP_PASSWORD")
    name = cfg_name or os.environ.get("GMAIL_SENDER_NAME") or env.get("GMAIL_SENDER_NAME")

    # 3. Check config/api_keys.json top-level
    if (not user or not pwd) and API_KEYS_PATH.exists():
        try:
            raw = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
            user = user or raw.get("gmail_user")
            pwd = pwd or raw.get("gmail_app_password")
            name = name or raw.get("gmail_sender_name")
        except Exception:
            pass

    # 4. Fallback defaults
    user = (user or DEFAULT_GMAIL_USER).strip()
    pwd = (pwd or DEFAULT_GMAIL_APP_PASSWORD).strip().replace(" ", "")
    name = (name or DEFAULT_SENDER_NAME).strip()

    return user, pwd, name


def load_contacts() -> dict:
    if not CONTACTS_PATH.exists():
        initial = {
            "hammad": "hammadnawaz519@gmail.com",
            "me": "hammadnawaz519@gmail.com",
            "self": "hammadnawaz519@gmail.com",
            "myself": "hammadnawaz519@gmail.com"
        }
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONTACTS_PATH.write_text(json.dumps(initial, indent=2), encoding="utf-8")
            return initial
        except Exception:
            return initial

    try:
        return json.loads(CONTACTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_recipient(recipient_input: str) -> tuple[str, str]:
    """Resolves contact alias, handle, or raw email address.
    Defaults to @gmail.com if no domain or provider is specified."""
    raw = (recipient_input or "").strip()
    if not raw:
        return "", ""

    # Check for <user@domain.com> format
    email_match = re.search(r"<([^>]+)>", raw)
    if email_match:
        email = email_match.group(1).strip()
        name = raw.split("<")[0].strip().strip('"').strip("'")
        return email.lower(), name or email

    # Handle voice transcripts like "username at domain.com" or "user at itu.edu.pk"
    at_match = re.search(r"^([\w\.\-\+]+)\s+(?:at|on|@)\s+([a-zA-Z0-9\.\-]+)$", raw, re.IGNORECASE)
    if at_match:
        handle = at_match.group(1).strip()
        domain = at_match.group(2).strip().lstrip("@")
        if "." not in domain and domain.lower() == "itu":
            domain = "itu.edu.pk"
        elif "." not in domain and domain.lower() in ("gmail", "google"):
            domain = "gmail.com"
        raw = f"{handle}@{domain}"

    # If it is already a valid email address with an @ and a domain
    if "@" in raw:
        parts = raw.split("@", 1)
        handle = parts[0].strip()
        domain = parts[1].strip()
        if "." not in domain and domain.lower() == "itu":
            domain = "itu.edu.pk"
        elif "." not in domain and domain.lower() in ("gmail", "google"):
            domain = "gmail.com"
        elif "." not in domain:
            domain = f"{domain}.com"
        email = f"{handle}@{domain}".lower()
        return email, handle.replace(".", " ").title()

    # Check contacts list
    contacts = load_contacts()
    normalized = raw.lower().replace(" ", "_")
    if normalized in contacts:
        return contacts[normalized].lower(), raw.title()

    for k, v in contacts.items():
        if k in normalized or normalized in k:
            return v.lower(), k.replace("_", " ").title()

    # If just a handle / username was provided (e.g. 'hamad54'), default to @gmail.com!
    clean_handle = re.sub(r"[^\w\.\-\+]", "", raw.lower())
    if clean_handle:
        return f"{clean_handle}@gmail.com", clean_handle.replace(".", " ").title()

    return raw.lower(), raw.title()


# ── THEMES & STYLING ──────────────────────────────────────────────────────────
THEMES = {
    "atelier_slate": {
        "name": "Atelier Slate (Refined Editorial Luxury)",
        "body_bg": "#F4F4F2",
        "container_bg": "#FFFFFF",
        "card_bg": "#F4F4F2",
        "border_color": "#E8E8E8",
        "border_outer": "#BBBFCA",
        "accent": "#495464",
        "accent_glow": "rgba(73, 84, 100, 0.08)",
        "accent_secondary": "#717D8F",
        "badge_bg": "#495464",
        "badge_border": "#495464",
        "badge_text": "#F4F4F2",
        "title_color": "#495464",
        "body_text": "#495464",
        "muted_text": "#717D8F",
        "quote_bg": "#F4F4F2",
        "quote_border": "#495464",
        "btn_bg": "#495464",
        "btn_text": "#F4F4F2",
        "btn_shadow": "none",
        "sys_badge": "AUREX",
        "pill_text": "INTELLIGENT ASSISTANT • OFFICIAL DISPATCH",
    },
    "cyber_aurex": {
        "name": "Cyber Aurex (Neon Cyan)",
        "body_bg": "#070b14",
        "container_bg": "#0f172a",
        "card_bg": "#131d35",
        "border_color": "#1e293b",
        "accent": "#00d4ff",
        "accent_glow": "rgba(0, 212, 255, 0.25)",
        "accent_secondary": "#3b82f6",
        "badge_bg": "rgba(0, 212, 255, 0.12)",
        "badge_border": "rgba(0, 212, 255, 0.4)",
        "badge_text": "#00d4ff",
        "title_color": "#f8fafc",
        "body_text": "#cbd5e1",
        "muted_text": "#64748b",
        "quote_bg": "#1a2542",
        "quote_border": "#00d4ff",
        "btn_bg": "linear-gradient(135deg, #00d4ff 0%, #2563eb 100%)",
        "btn_text": "#ffffff",
        "btn_shadow": "0 6px 20px rgba(0, 212, 255, 0.35)",
        "sys_badge": "⚡ AUREX INTELLIGENCE SYSTEM",
        "pill_text": "● SECURE NEURAL TRANSMISSION",
    },
    "aurora_purple": {
        "name": "Aurora Purple (Galactic Glow)",
        "body_bg": "#090614",
        "container_bg": "#140e29",
        "card_bg": "#1d143b",
        "border_color": "#2c1c54",
        "accent": "#c084fc",
        "accent_glow": "rgba(192, 132, 252, 0.25)",
        "accent_secondary": "#ec4899",
        "badge_bg": "rgba(192, 132, 252, 0.12)",
        "badge_border": "rgba(192, 132, 252, 0.4)",
        "badge_text": "#c084fc",
        "title_color": "#faf5ff",
        "body_text": "#e9d5ff",
        "muted_text": "#7e6c99",
        "quote_bg": "#251b47",
        "quote_border": "#c084fc",
        "btn_bg": "linear-gradient(135deg, #c084fc 0%, #ec4899 100%)",
        "btn_text": "#ffffff",
        "btn_shadow": "0 6px 20px rgba(192, 132, 252, 0.35)",
        "sys_badge": "✦ AUREX AURORA PROTOCOL",
        "pill_text": "● QUANTUM LINK ACTIVE",
    },
    "executive_modern": {
        "name": "Executive Modern (Sleek Dark)",
        "body_bg": "#0b0f19",
        "container_bg": "#111827",
        "card_bg": "#1f2937",
        "border_color": "#374151",
        "accent": "#38bdf8",
        "accent_glow": "rgba(56, 189, 248, 0.2)",
        "accent_secondary": "#818cf8",
        "badge_bg": "rgba(56, 189, 248, 0.1)",
        "badge_border": "rgba(56, 189, 248, 0.35)",
        "badge_text": "#38bdf8",
        "title_color": "#ffffff",
        "body_text": "#e5e7eb",
        "muted_text": "#9ca3af",
        "quote_bg": "#283548",
        "quote_border": "#38bdf8",
        "btn_bg": "linear-gradient(135deg, #38bdf8 0%, #6366f1 100%)",
        "btn_text": "#ffffff",
        "btn_shadow": "0 6px 20px rgba(56, 189, 248, 0.3)",
        "sys_badge": "◈ AUREX EXECUTIVE SUITE",
        "pill_text": "● VERIFIED OFFICIAL DISPATCH",
    },
    "clean_light": {
        "name": "Clean Light (Professional Editorial)",
        "body_bg": "#f1f5f9",
        "container_bg": "#ffffff",
        "card_bg": "#f8fafc",
        "border_color": "#e2e8f0",
        "accent": "#0284c7",
        "accent_glow": "rgba(2, 132, 199, 0.15)",
        "accent_secondary": "#0369a1",
        "badge_bg": "#e0f2fe",
        "badge_border": "#bae6fd",
        "badge_text": "#0284c7",
        "title_color": "#0f172a",
        "body_text": "#334155",
        "muted_text": "#64748b",
        "quote_bg": "#f1f5f9",
        "quote_border": "#0284c7",
        "btn_bg": "linear-gradient(135deg, #0284c7 0%, #0369a1 100%)",
        "btn_text": "#ffffff",
        "btn_shadow": "0 4px 15px rgba(2, 132, 199, 0.25)",
        "sys_badge": "⚡ AUREX COMMUNICATIONS",
        "pill_text": "● OFFICIAL TRANSMISSION",
    },
}


def _markdown_to_html(text: str, theme: dict) -> str:
    """Converts markdown paragraphs, bullet points, quotes, and links to styled HTML."""
    if not text:
        return ""

    lines = text.strip().split("\n")
    html_parts = []
    in_list = False
    in_quote = False
    quote_buffer = []

    def flush_quote():
        nonlocal in_quote, quote_buffer
        if in_quote and quote_buffer:
            q_text = "<br>".join(quote_buffer)
            html_parts.append(
                f'<div style="background-color: {theme["quote_bg"]}; border-left: 4px solid {theme["quote_border"]}; '
                f'padding: 14px 18px; margin: 18px 0; border-radius: 0 10px 10px 0; font-style: italic; '
                f'color: {theme["body_text"]}; line-height: 1.6; font-size: 14px;">{q_text}</div>'
            )
            quote_buffer = []
            in_quote = False

    def flush_list():
        nonlocal in_list
        if in_list:
            html_parts.append('</ul>')
            in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_quote()
            flush_list()
            continue

        if stripped.startswith(">"):
            flush_list()
            in_quote = True
            content = _format_inline(stripped[1:].strip(), theme)
            quote_buffer.append(content)
            continue
        else:
            flush_quote()

        if stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                html_parts.append(f'<ul style="margin: 14px 0; padding-left: 24px; color: {theme["body_text"]};">')
                in_list = True
            item_text = _format_inline(stripped[2:].strip(), theme)
            html_parts.append(
                f'<li style="margin-bottom: 8px; line-height: 1.6; font-size: 15px;">'
                f'<span style="color: {theme["body_text"]};">{item_text}</span></li>'
            )
            continue
        else:
            flush_list()

        if stripped.startswith("### "):
            h = _format_inline(stripped[4:], theme)
            html_parts.append(f'<h3 style="color: {theme["title_color"]}; font-size: 17px; font-weight: 700; margin: 20px 0 10px 0;">{h}</h3>')
            continue
        elif stripped.startswith("## "):
            h = _format_inline(stripped[3:], theme)
            html_parts.append(f'<h2 style="color: {theme["title_color"]}; font-size: 19px; font-weight: 700; margin: 22px 0 12px 0;">{h}</h2>')
            continue
        elif stripped.startswith("# "):
            h = _format_inline(stripped[2:], theme)
            html_parts.append(f'<h1 style="color: {theme["title_color"]}; font-size: 22px; font-weight: 800; margin: 24px 0 14px 0;">{h}</h1>')
            continue

        if stripped in ("---", "***", "___"):
            html_parts.append(f'<hr style="border: none; border-top: 1px solid {theme["border_color"]}; margin: 24px 0;">')
            continue

        p = _format_inline(stripped, theme)
        html_parts.append(f'<p style="margin: 0 0 14px 0; font-size: 15px; line-height: 1.7; color: {theme["body_text"]};">{p}</p>')

    flush_quote()
    flush_list()

    return "\n".join(html_parts)


def _format_inline(text: str, theme: dict) -> str:
    """Replaces bold, italic, code, and links with styled HTML spans."""
    text = re.sub(
        r"\*\*(.+?)\*\*",
        r'<strong style="color: ' + theme["title_color"] + r'; font-weight: 700;">\1</strong>',
        text
    )
    text = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        r'<em style="color: ' + theme["body_text"] + r'; font-style: italic;">\1</em>',
        text
    )
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background-color: ' + theme["quote_bg"] + r'; color: ' + theme["accent"] +
        r'; padding: 3px 7px; border-radius: 5px; font-family: monospace; font-size: 13px; border: 1px solid ' +
        theme["border_color"] + r';">\1</code>',
        text
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" style="color: ' + theme["accent"] +
        r'; text-decoration: none; border-bottom: 1px dashed ' + theme["accent"] +
        r'; font-weight: 600;">\1</a>',
        text
    )
    return text


def build_html_email(
    to_name: str,
    to_email: str,
    subject: str,
    body: str,
    theme_key: str = "atelier_slate",
    button_text: str | None = None,
    button_url: str | None = None,
    sender_name: str | None = None,
    sender_email: str | None = None,
) -> str:
    """Generates the clean, refined editorial HTML email."""
    theme = THEMES.get(theme_key, THEMES["atelier_slate"])
    now_str = datetime.now().strftime("%B %d, %Y • %I:%M %p")
    sender_name = sender_name or "Hammad Nawaz"
    sender_email = sender_email or DEFAULT_GMAIL_USER

    formatted_body = _markdown_to_html(body, theme)

    raw_preview = re.sub(r"[#*`\[\]()]", "", body).strip()
    preheader_text = raw_preview[:120] if raw_preview else f"Official dispatch from {sender_name}."

    button_html = ""
    if button_text and button_url:
        button_html = f"""
          <!-- CALL TO ACTION BUTTON -->
          <tr>
            <td align="center" style="padding: 10px 28px 24px 28px; text-align: center;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
                <tr>
                  <td align="center" style="background-color: {theme['btn_bg']}; border-radius: 2px;">
                    <a href="{button_url}" target="_blank" class="cta-btn" style="display: inline-block; font-size: 11px; font-weight: 600; letter-spacing: 0.18em; text-transform: uppercase; color: {theme['btn_text']}; text-decoration: none; padding: 13px 34px; border: 1px solid {theme['btn_bg']}; border-radius: 2px;">
                      {button_text} &rarr;
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        """

    border_outer = theme.get("border_outer", theme["border_color"])

    return f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta name="x-apple-disable-message-reformatting" />
  <meta name="format-detection" content="telephone=no, date=no, address=no, email=no" />
  <meta name="color-scheme" content="light" />
  <meta name="supported-color-schemes" content="light" />
  <title>{subject}</title>
  <style type="text/css">
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }}
    body {{
      margin: 0;
      padding: 0;
      width: 100% !important;
      height: 100% !important;
      background-color: {theme['body_bg']};
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }}
    .cta-btn:hover {{
      background-color: #363E4B !important;
    }}
    @media only screen and (max-width: 600px) {{
      .email-container {{ width: 100% !important; max-width: 100% !important; }}
      .content-padding {{ padding: 24px 16px !important; }}
      .mobile-stack {{ display: block !important; width: 100% !important; text-align: left !important; }}
      .mobile-padding-top {{ padding-top: 10px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: {theme['body_bg']}; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; -webkit-text-size-adjust: none;">
  <!-- Anti-Spam Deliverability Preheader -->
  <div style="display: none; font-size: 1px; color: #666666; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all; visibility: hidden;">
    {preheader_text}
  </div>
  <div style="display: none; font-size: 1px; line-height: 1px; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden; mso-hide: all;">
    &zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;
  </div>

  <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {theme['body_bg']}; padding: 36px 12px;">
    <tr>
      <td align="center">
        <!-- Main Container (max-width 580px) -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" class="email-container" style="max-width: 580px; background-color: {theme['container_bg']}; border: 1px solid {border_outer}; border-radius: 2px; overflow: hidden;">
          
          <!-- TOP ACCENT BAR -->
          <tr>
            <td style="background-color: {theme['accent']}; height: 4px; line-height: 4px; font-size: 1px;">&nbsp;</td>
          </tr>

          <!-- HEADER / BRAND BADGE -->
          <tr>
            <td align="center" style="padding: 32px 24px 18px 24px; text-align: center; background-color: {theme['container_bg']};">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 0 auto;">
                <tr>
                  <td align="center" style="background-color: {theme['badge_bg']}; padding: 9px 30px; border-radius: 2px;">
                    <span style="font-family: 'Cormorant Garamond', 'Georgia', serif; font-size: 20px; font-weight: 400; letter-spacing: 0.35em; color: {theme['badge_text']}; text-transform: uppercase; margin-left: 0.35em; display: inline-block;">
                      {theme['sys_badge']}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- HERO BANNER / SUBJECT -->
          <tr>
            <td align="center" style="padding: 10px 28px 20px 28px; text-align: center;">
              <h1 style="font-family: 'Cormorant Garamond', 'Georgia', serif; font-size: 24px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: {theme['title_color']}; margin: 0 0 8px 0; line-height: 1.35;">
                {subject}
              </h1>
            </td>
          </tr>

          <!-- META CARD -->
          <tr>
            <td style="padding: 0 28px 22px 28px;">
              <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {theme['card_bg']}; border: 1px solid {theme['border_color']}; padding: 12px 18px; border-radius: 2px;">
                <tr>
                  <td style="text-align: left; vertical-align: middle;">
                    <span style="font-size: 12px; font-weight: 600; color: {theme['title_color']}; letter-spacing: 0.03em;">From: {sender_name}</span>
                  </td>
                  <td style="text-align: right; vertical-align: middle;">
                    <span style="font-size: 11px; color: {theme['muted_text']}; letter-spacing: 0.03em;">{now_str}</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- DIVIDER -->
          <tr>
            <td style="padding: 0 28px;">
              <div style="border-top: 1px solid {theme['border_color']}; font-size: 1px; line-height: 1px; margin-bottom: 22px;">&nbsp;</div>
            </td>
          </tr>

          <!-- BODY CONTENT -->
          <tr>
            <td style="padding: 0 28px 20px 28px; font-size: 14px; line-height: 1.75; color: {theme['body_text']};">
              {formatted_body}
            </td>
          </tr>

          {button_html}

          <!-- SIGN-OFF -->
          <tr>
            <td style="padding: 10px 28px 28px 28px;">
              <div style="font-size: 12px; color: {theme['muted_text']}; margin-bottom: 4px;">Warm regards,</div>
              <div style="font-family: 'Cormorant Garamond', 'Georgia', serif; font-size: 18px; font-weight: 600; color: {theme['title_color']};">
                {sender_name}
              </div>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td align="center" style="padding: 20px 28px; text-align: center; background-color: {theme['card_bg']};">
              <p style="font-size: 10px; color: {theme.get('border_outer', '#BBBFCA')}; letter-spacing: 0.05em; margin: 0;">
                &copy; 2026 AUREX. All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _log_player(msg: str, player=None):
    try:
        print(f"[AUREX Plugin: Gmail] {msg}")
    except UnicodeEncodeError:
        print(f"[AUREX Plugin: Gmail] {msg.encode('ascii', errors='replace').decode('ascii')}")
    if player and hasattr(player, "write_log"):
        try:
            player.write_log(f"AUREX: {msg}")
        except Exception:
            pass


def send_email(
    to: str,
    subject: str,
    body: str,
    theme: str = "atelier_slate",
    button_text: str | None = None,
    button_url: str | None = None,
    player=None,
) -> tuple[bool, str]:
    """Sends email via Gmail SSL SMTP."""
    to_email, to_name = resolve_recipient(to)

    if not to_email or "@" not in to_email:
        return False, f"Invalid recipient email address: '{to}'"

    user_email, app_password, sender_name = get_credentials()

    _log_player(f"📧 Preparing UI email ({theme}) for {to_name} <{to_email}>...", player)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{user_email}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name != to_email else to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="aurex.local")

    # Plain text fallback
    plain_text = f"From: {sender_name} <{user_email}>\nTo: {to_name} <{to_email}>\nSubject: {subject}\n\n{body}\n\n[Sent via AUREX Intelligence]"
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))

    # Rich UI HTML
    html_content = build_html_email(
        to_name=to_name,
        to_email=to_email,
        subject=subject,
        body=body,
        theme_key=theme,
        button_text=button_text,
        button_url=button_url,
        sender_name=sender_name,
        sender_email=user_email
    )
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        _log_player(f"🚀 Connecting to smtp.gmail.com:465 via SSL...", player)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=25) as server:
            server.login(user_email, app_password)
            server.sendmail(user_email, [to_email], msg.as_string())

        _log_player(f"✅ Email successfully delivered to {to_name} ({to_email})!", player)

        # Automatically remember/record sent email (sent_emails.json + cognitive memory)
        _record_sent_email(
            to_name=to_name,
            to_email=to_email,
            subject=subject,
            body=body,
            theme=theme,
            sender_name=sender_name,
            msg_id=msg["Message-ID"]
        )

        return True, f"Email delivered to {to_name} ({to_email}) with subject '{subject}'."

    except smtplib.SMTPAuthenticationError as e:
        err = f"Gmail SMTP Authentication failed. Please verify the 16-character App Password. Error: {e}"
        _log_player(f"❌ {err}", player)
        return False, err
    except Exception as e:
        err = f"Failed to send email to {to_email}: {e}"
        _log_player(f"❌ {err}", player)
        return False, err


# ── SENT EMAIL MEMORY & HISTORY ───────────────────────────────────────────────

def _record_sent_email(
    to_name: str,
    to_email: str,
    subject: str,
    body: str,
    theme: str,
    sender_name: str,
    msg_id: str | None = None
) -> None:
    """
    Saves a persistent structured record of every sent email into memory/sent_emails.json,
    and simultaneously updates AUREX long-term cognitive memory so the assistant remembers
    whom it emailed, when, and what was said during future voice conversations.
    """
    now = datetime.now()
    entry = {
        "id": str(msg_id or make_msgid(domain="aurex.local")),
        "timestamp": now.isoformat(),
        "date_str": now.strftime("%B %d, %Y at %I:%M %p"),
        "to_name": to_name,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "theme": theme,
        "sender": sender_name,
    }

    # 1. Persistent dedicated JSON store in memory/sent_emails.json
    try:
        SENT_EMAILS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _SENT_LOCK:
            history = []
            if SENT_EMAILS_PATH.exists():
                try:
                    data = json.loads(SENT_EMAILS_PATH.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        history = data
                except Exception:
                    history = []
            history.append(entry)
            if len(history) > 500:
                history = history[-500:]
            SENT_EMAILS_PATH.write_text(
                json.dumps(history, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"[Gmail History] 💾 Recorded sent email to {to_name} ({to_email}) in {SENT_EMAILS_PATH.name}")
    except Exception as e:
        print(f"[Gmail History] ⚠️ Failed saving to {SENT_EMAILS_PATH}: {e}")

    # 2. Cognitive long-term memory update (queried by recall_memory across all sessions)
    try:
        from memory.memory_manager import update_memory
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", to_name or to_email).strip("_").lower()[:20]
        time_tag = now.strftime("%Y%m%d_%H%M%S")
        snippet = (body[:150] + "…") if len(body) > 150 else body
        summary_val = (
            f"Sent email to {to_name} ({to_email}) on {now.strftime('%B %d, %Y at %I:%M %p')} "
            f"with subject '{subject}'. Content: {snippet}"
        )
        update_memory({
            "notes": {
                f"sent_email_{clean_name}_{time_tag}": {
                    "value": summary_val
                }
            }
        })
        print(f"[Gmail Memory] 🧠 Synced sent email note into AUREX cognitive memory.")
    except Exception as e:
        print(f"[Gmail Memory] ⚠️ Failed syncing to long_term.json: {e}")


def get_sent_emails(query: str = "", limit: int = 5) -> list[dict]:
    """Retrieve sent email records from memory/sent_emails.json, newest first."""
    if not SENT_EMAILS_PATH.exists():
        return []
    with _SENT_LOCK:
        try:
            data = json.loads(SENT_EMAILS_PATH.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
        except Exception:
            return []

    q = (query or "").strip().lower()
    if q:
        filtered = [
            e for e in data
            if q in str(e.get("to_name", "")).lower()
            or q in str(e.get("to_email", "")).lower()
            or q in str(e.get("subject", "")).lower()
            or q in str(e.get("body", "")).lower()
        ]
    else:
        filtered = data

    return list(reversed(filtered))[:limit]


# ── PLUGIN REGISTRATION & ENTRYPOINT ─────────────────────────────────────────

PLUGIN = {
    "name": "gmail",
    "description": (
        "Sends an email via Gmail using a refined luxury editorial HTML UI template, "
        "and automatically remembers all sent emails in memory/sent_emails.json (whom, when, subject, and content). "
        "Can also retrieve or list sent emails when user asks what emails were sent or checks sent history. "
        "Use this tool whenever the user asks to send an email, mail someone, check sent emails, or see who was emailed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Action to perform: 'send' (default) to send a new email, or 'history' / 'list' to check previously sent emails."
            },
            "to": {
                "type": "STRING",
                "description": (
                    "Recipient email address or handle. If user provides only a username/handle (e.g. 'hamad54'), "
                    "pass it directly — it automatically defaults to @gmail.com. Do NOT ask user to say '@gmail.com'. "
                    "If user explicitly specifies a different domain (e.g. '@itu.edu.pk' or 'hamad54@itu.edu.pk'), provide that domain. "
                    "If user mentions an alternate system or institution without full address, clarify briefly whether to send to their Gmail or that system."
                )
            },
            "subject": {
                "type": "STRING",
                "description": "The subject line of the email (for send action)"
            },
            "body": {
                "type": "STRING",
                "description": "Content of the email message (for send action). Supports markdown."
            },
            "query": {
                "type": "STRING",
                "description": "Optional search filter (e.g. recipient name, subject keyword) when checking sent email history"
            },
            "theme": {
                "type": "STRING",
                "description": "Optional UI theme: 'atelier_slate' (default elegant editorial luxury), 'cyber_aurex', 'executive_modern', or 'clean_light'"
            },
            "button_text": {
                "type": "STRING",
                "description": "Optional call-to-action button text (e.g. 'View Report', 'Reply')"
            },
            "button_url": {
                "type": "STRING",
                "description": "Optional URL link for the call-to-action button"
            }
        },
        "required": []
    }
}

PLUGIN_SETTINGS = {
    "namespace": "gmail",
    "title": "Gmail Settings",
    "fields": [
        {
            "key": "user",
            "label": "Gmail Address",
            "type": "text",
            "placeholder": "hammadnawaz519@gmail.com",
            "help": "Your Google email address"
        },
        {
            "key": "app_password",
            "label": "Google App Password (16-char)",
            "type": "password",
            "placeholder": "rpyu qgwy pbed bldh",
            "help": "Google App Password from Security settings"
        },
        {
            "key": "sender_name",
            "label": "Display Sender Name",
            "type": "text",
            "placeholder": "Hammad Nawaz (via AUREX)",
            "help": "Name shown in the 'From' header"
        }
    ]
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Entrypoint called by AUREX Plugin Loader / Gemini Live.
    """
    params = parameters or {}
    action = str(params.get("action", "send")).strip().lower()
    to = params.get("to", "").strip()
    subject = params.get("subject", "").strip()
    body = params.get("body", "").strip()
    query = str(params.get("query", "")).strip()
    theme = params.get("theme", "atelier_slate").strip().lower()
    button_text = params.get("button_text")
    button_url = params.get("button_url")

    # History / Lookup check: if user asked about previous emails sent
    is_history_query = any(k in action for k in ("history", "list", "sent", "check", "log", "find", "search", "recent")) or (not body and (to or query) and not subject)
    if is_history_query:
        q = query or to
        records = get_sent_emails(query=q, limit=5)
        if not records:
            if q:
                return f"Sir, I checked the sent email records and found no sent emails matching '{q}'."
            return "Sir, I checked the records and no emails have been recorded as sent yet."

        lines = [f"Sir, here are the recent sent email records:"]
        for i, rec in enumerate(records, 1):
            lines.append(
                f"{i}. To: {rec.get('to_name')} <{rec.get('to_email')}>\n"
                f"   When: {rec.get('date_str')}\n"
                f"   Subject: '{rec.get('subject')}'\n"
                f"   Content: {str(rec.get('body', ''))[:120]}..."
            )
        res_text = "\n".join(lines)
        if player and hasattr(player, "show_content"):
            player.show_content("SENT EMAIL HISTORY", res_text)
        return res_text

    if not to:
        return "Sir, please specify who you would like me to send the email to."

    if not body:
        return f"Sir, what message would you like me to include in the email to {to}?"

    if not subject:
        subject = "Message from Hammad Nawaz"

    if theme not in THEMES:
        theme = "atelier_slate"

    ok, msg = send_email(
        to=to,
        subject=subject,
        body=body,
        theme=theme,
        button_text=button_text,
        button_url=button_url,
        player=player
    )

    to_email, _ = resolve_recipient(to)
    target_addr = to_email or to

    if ok:
        return f"Sir, I have dispatched your email to {target_addr} with the subject '{subject}'. It has been delivered and saved to your sent records."
    else:
        return f"Sir, I encountered an issue sending the email to {target_addr}: {msg}"
