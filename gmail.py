"""
AUREX GMAIL COMMUNICATOR
========================
Autonomous Intelligent Email Dispatcher for AUREX AI Assistant.
Generates stunning, responsive, high-end HTML UI emails with customizable themes.

Features:
- Integrated with AUREX Live Action Registry (auto-discovered tool)
- High-fidelity modern UI email templates (Cyber Aurex, Executive Modern, Aurora Purple, Clean Light)
- Markdown-to-HTML rich formatting for email body
- AI-powered natural language command parsing (via Gemini)
- Interactive CLI & direct command-line arguments
- Contact resolution from config/contacts.json
- On-screen HUD log & content panel integration with AUREX UI
"""

import os
import sys
import json
import re
import ssl
import smtplib
import argparse
import webbrowser
import tempfile
from pathlib import Path
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate, make_msgid

# Force UTF-8 on Windows consoles to prevent cp1252 charmap encode errors
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── BASE PATHS & CONFIG ────────────────────────────────────────────────────────
def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR = _get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_KEYS_PATH = CONFIG_DIR / "api_keys.json"
CONTACTS_PATH = CONFIG_DIR / "contacts.json"
ENV_PATH = BASE_DIR / ".env"

# Fallback defaults (provided by user)
DEFAULT_GMAIL_USER = "hammadnawaz519@gmail.com"
DEFAULT_GMAIL_APP_PASSWORD = "rpyu qgwy pbed bldh"
DEFAULT_SENDER_NAME = "Hammad Nawaz (via AUREX)"


def load_env_vars() -> dict:
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


def get_gmail_credentials() -> tuple[str, str, str]:
    """Returns (user_email, app_password, sender_name)."""
    env_vars = load_env_vars()

    # 1. Environment variables / .env
    user = os.environ.get("GMAIL_USER") or env_vars.get("GMAIL_USER")
    app_pwd = os.environ.get("GMAIL_APP_PASSWORD") or env_vars.get("GMAIL_APP_PASSWORD")
    sender_name = os.environ.get("GMAIL_SENDER_NAME") or env_vars.get("GMAIL_SENDER_NAME")

    # 2. config/api_keys.json
    if (not user or not app_pwd) and API_KEYS_PATH.exists():
        try:
            cfg = json.loads(API_KEYS_PATH.read_text(encoding="utf-8"))
            user = user or cfg.get("gmail_user")
            app_pwd = app_pwd or cfg.get("gmail_app_password")
            sender_name = sender_name or cfg.get("gmail_sender_name")
        except Exception:
            pass

    # 3. Fallbacks
    user = (user or DEFAULT_GMAIL_USER).strip()
    app_pwd = (app_pwd or DEFAULT_GMAIL_APP_PASSWORD).strip().replace(" ", "")
    sender_name = (sender_name or DEFAULT_SENDER_NAME).strip()

    return user, app_pwd, sender_name


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


def save_contact(name: str, email: str) -> bool:
    contacts = load_contacts()
    contacts[name.strip().lower()] = email.strip().lower()
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONTACTS_PATH.write_text(json.dumps(contacts, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Contacts] Error saving contact: {e}")
        return False


def resolve_recipient(recipient_input: str) -> tuple[str, str]:
    """
    Resolves recipient string to (email_address, display_name).
    Checks contacts.json, or handles raw email addresses.
    """
    raw = recipient_input.strip()
    # Check if raw input contains <email@example.com>
    email_match = re.search(r"<([^>]+)>", raw)
    if email_match:
        email = email_match.group(1).strip()
        name = raw.split("<")[0].strip().strip('"').strip("'")
        return email, name or email

    # Direct email regex
    if "@" in raw and "." in raw:
        return raw.lower(), raw.split("@")[0].title()

    # Look up in contacts
    contacts = load_contacts()
    normalized = raw.lower().replace(" ", "_")
    if normalized in contacts:
        return contacts[normalized], raw.title()

    # Partial match in contacts
    for k, v in contacts.items():
        if k in normalized or normalized in k:
            return v, k.replace("_", " ").title()

    # If it's a plain name without domain, default or error
    return raw, raw.title()


# ── THEMES & STYLING ──────────────────────────────────────────────────────────
THEMES = {
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

        # Handle empty line
        if not stripped:
            flush_quote()
            flush_list()
            continue

        # Handle Blockquotes
        if stripped.startswith(">"):
            flush_list()
            in_quote = True
            content = stripped[1:].strip()
            # Process inline formatting
            content = _format_inline(content, theme)
            quote_buffer.append(content)
            continue
        else:
            flush_quote()

        # Handle Bullet lists
        if stripped.startswith(("- ", "* ", "• ")):
            if not in_list:
                html_parts.append(f'<ul style="margin: 14px 0; padding-left: 24px; color: {theme["body_text"]};">')
                in_list = True
            item_text = stripped[2:].strip()
            item_text = _format_inline(item_text, theme)
            html_parts.append(
                f'<li style="margin-bottom: 8px; line-height: 1.6; font-size: 15px;">'
                f'<span style="color: {theme["body_text"]};">{item_text}</span></li>'
            )
            continue
        else:
            flush_list()

        # Handle Headings
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

        # Handle Dividers
        if stripped in ("---", "***", "___"):
            html_parts.append(f'<hr style="border: none; border-top: 1px solid {theme["border_color"]}; margin: 24px 0;">')
            continue

        # Normal paragraph
        p = _format_inline(stripped, theme)
        html_parts.append(f'<p style="margin: 0 0 14px 0; font-size: 15px; line-height: 1.7; color: {theme["body_text"]};">{p}</p>')

    flush_quote()
    flush_list()

    return "\n".join(html_parts)


def _format_inline(text: str, theme: dict) -> str:
    """Replaces bold, italic, code, and links with styled HTML spans."""
    # Bold **text**
    text = re.sub(
        r"\*\*(.+?)\*\*",
        r'<strong style="color: ' + theme["title_color"] + r'; font-weight: 700;">\1</strong>',
        text
    )
    # Italic *text* or _text_
    text = re.sub(
        r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)",
        r'<em style="color: ' + theme["body_text"] + r'; font-style: italic;">\1</em>',
        text
    )
    # Inline code `code`
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background-color: ' + theme["quote_bg"] + r'; color: ' + theme["accent"] +
        r'; padding: 3px 7px; border-radius: 5px; font-family: monospace; font-size: 13px; border: 1px solid ' +
        theme["border_color"] + r';">\1</code>',
        text
    )
    # Markdown links [text](url)
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
    theme_key: str = "cyber_aurex",
    button_text: str | None = None,
    button_url: str | None = None,
    sender_name: str | None = None,
    sender_email: str | None = None,
) -> str:
    """Generates the full modern UI HTML email."""
    theme = THEMES.get(theme_key, THEMES["cyber_aurex"])
    now_str = datetime.now().strftime("%B %d, %Y • %I:%M %p")
    sender_name = sender_name or "Hammad Nawaz"
    sender_email = sender_email or DEFAULT_GMAIL_USER

    formatted_body = _markdown_to_html(body, theme)

    # Optional Button CTA
    button_html = ""
    if button_text and button_url:
        button_html = f"""
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="margin: 28px 0 16px 0;">
            <tr>
                <td align="left">
                    <a href="{button_url}" target="_blank" style="display: inline-block; padding: 14px 32px; background: {theme['btn_bg']}; color: {theme['btn_text']}; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; letter-spacing: 0.5px; box-shadow: {theme['btn_shadow']}; text-transform: uppercase;">
                        {button_text} &rarr;
                    </a>
                </td>
            </tr>
        </table>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>{subject}</title>
    <!--[if mso]>
    <style type="text/css">
    body, table, td {{font-family: Arial, Helvetica, sans-serif !important;}}
    </style>
    <![endif]-->
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=Inter:wght@400;500;600;700&display=swap');
        body {{
            margin: 0;
            padding: 0;
            background-color: {theme['body_bg']};
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            -webkit-font-smoothing: antialiased;
            color: {theme['body_text']};
        }}
        table {{
            border-collapse: collapse;
        }}
        img {{
            border: 0;
            line-height: 100%;
            outline: none;
            text-decoration: none;
        }}
        .mobile-wrap {{
            width: 100% !important;
            max-width: 620px !important;
        }}
    </style>
</head>
<body style="margin: 0; padding: 30px 10px; background-color: {theme['body_bg']};">
    <center>
        <!-- Top Outer Wrapper -->
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 620px; margin: 0 auto;">
            
            <!-- SYSTEM HEADER BADGE -->
            <tr>
                <td style="padding-bottom: 14px;">
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td align="left">
                                <span style="display: inline-block; background-color: {theme['badge_bg']}; border: 1px solid {theme['badge_border']}; color: {theme['badge_text']}; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; padding: 5px 12px; border-radius: 20px; text-transform: uppercase;">
                                    {theme['sys_badge']}
                                </span>
                            </td>
                            <td align="right">
                                <span style="font-size: 11px; color: {theme['muted_text']}; font-weight: 600; letter-spacing: 0.5px;">
                                    {theme['pill_text']}
                                </span>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>

            <!-- MAIN CONTAINER CARD -->
            <tr>
                <td style="background-color: {theme['container_bg']}; border: 1px solid {theme['border_color']}; border-radius: 16px; overflow: hidden; box-shadow: 0 20px 40px -15px {theme['accent_glow']};">
                    
                    <!-- TOP GLOW ACCENT BAR -->
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%">
                        <tr>
                            <td height="4" style="background: linear-gradient(90deg, {theme['accent']}, {theme['accent_secondary']}); font-size: 0; line-height: 0;">&nbsp;</td>
                        </tr>
                    </table>

                    <!-- CARD PADDING WRAPPER -->
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="padding: 32px 32px 28px 32px;">
                        
                        <!-- SENDER & RECIPIENT META ROW -->
                        <tr>
                            <td style="padding-bottom: 24px;">
                                <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {theme['card_bg']}; border: 1px solid {theme['border_color']}; border-radius: 12px; padding: 14px 18px;">
                                    <tr>
                                        <td>
                                            <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: {theme['muted_text']}; font-weight: 700; margin-bottom: 4px;">
                                                TRANSMISSION DISPATCH
                                            </div>
                                            <div style="font-size: 13px; color: {theme['title_color']};">
                                                <strong>From:</strong> {sender_name} &lt;<span style="color: {theme['accent']};">{sender_email}</span>&gt;
                                            </div>
                                            <div style="font-size: 13px; color: {theme['body_text']}; margin-top: 2px;">
                                                <strong>To:</strong> {to_name} &lt;<span style="color: {theme['accent']};">{to_email}</span>&gt;
                                            </div>
                                        </td>
                                        <td align="right" valign="top">
                                            <span style="font-size: 11px; color: {theme['muted_text']}; font-family: monospace;">
                                                {now_str}
                                            </span>
                                        </td>
                                    </tr>
                                </table>
                            </td>
                        </tr>

                        <!-- SUBJECT TITLE -->
                        <tr>
                            <td style="padding-bottom: 20px;">
                                <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 1.5px; color: {theme['accent']}; font-weight: 800; margin-bottom: 6px;">
                                    SUBJECT LINE
                                </div>
                                <h1 style="margin: 0; font-family: 'Outfit', 'Inter', sans-serif; font-size: 24px; font-weight: 800; line-height: 1.3; color: {theme['title_color']}; letter-spacing: -0.3px;">
                                    {subject}
                                </h1>
                            </td>
                        </tr>

                        <!-- DIVIDER -->
                        <tr>
                            <td style="padding-bottom: 24px;">
                                <div style="height: 1px; width: 100%; background: linear-gradient(90deg, {theme['border_color']}, {theme['accent_glow']}, {theme['border_color']});"></div>
                            </td>
                        </tr>

                        <!-- EMAIL BODY CONTENT -->
                        <tr>
                            <td style="padding-bottom: 12px;">
                                {formatted_body}
                                {button_html}
                            </td>
                        </tr>

                        <!-- SIGN-OFF GREETING -->
                        <tr>
                            <td style="padding-top: 16px; border-top: 1px solid {theme['border_color']};">
                                <p style="margin: 0; font-size: 14px; color: {theme['body_text']};">
                                    Best regards,<br>
                                    <strong style="color: {theme['title_color']}; font-size: 15px;">{sender_name}</strong>
                                </p>
                            </td>
                        </tr>

                    </table>

                    <!-- FOOTER SECURITY / BRANDING -->
                    <table role="presentation" border="0" cellpadding="0" cellspacing="0" width="100%" style="background-color: {theme['card_bg']}; border-top: 1px solid {theme['border_color']}; padding: 20px 32px;">
                        <tr>
                            <td align="left">
                                <div style="font-size: 11px; color: {theme['muted_text']}; font-weight: 600; line-height: 1.5;">
                                    Generated & Dispatched autonomously via <strong style="color: {theme['accent']};">AUREX Intelligence Core</strong>.
                                </div>
                                <div style="font-size: 10px; color: {theme['muted_text']}; margin-top: 2px;">
                                    🔒 256-Bit SSL/TLS Encrypted Transmission • Authenticated Google SMTP Relay
                                </div>
                            </td>
                            <td align="right" valign="middle">
                                <span style="font-size: 18px; filter: drop-shadow(0 0 8px {theme['accent']});">⚡</span>
                            </td>
                        </tr>
                    </table>

                </td>
            </tr>

            <!-- FOOTER NOTICE -->
            <tr>
                <td align="center" style="padding-top: 20px;">
                    <p style="margin: 0; font-size: 11px; color: {theme['muted_text']}; line-height: 1.5;">
                        This email was sent on behalf of Hammad Nawaz using AUREX AI Desktop Assistant.<br>
                        Recipient: <span style="color: {theme['accent']};">{to_email}</span> • Time: {now_str}
                    </p>
                </td>
            </tr>

        </table>
    </center>
</body>
</html>
"""
    return html


def build_plain_text(
    to_name: str,
    to_email: str,
    subject: str,
    body: str,
    sender_name: str | None = None,
    sender_email: str | None = None,
) -> str:
    """Builds clean plain-text fallback for non-HTML mail clients."""
    sender_name = sender_name or "Hammad Nawaz"
    sender_email = sender_email or DEFAULT_GMAIL_USER
    now_str = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    return f"""===================================================================
AUREX SECURE TRANSMISSION
===================================================================
From:    {sender_name} <{sender_email}>
To:      {to_name} <{to_email}>
Date:    {now_str}
Subject: {subject}
===================================================================

{body}

-------------------------------------------------------------------
Best regards,
{sender_name}

[Sent autonomously via AUREX AI Desktop Core for Hammad Nawaz]
===================================================================
"""


# ── CORE EMAIL SENDER ────────────────────────────────────────────────────────
def send_email(
    to: str,
    subject: str,
    body: str,
    theme: str = "cyber_aurex",
    button_text: str | None = None,
    button_url: str | None = None,
    attachments: list[str] | None = None,
    sender_name: str | None = None,
    player=None,
) -> dict:
    """
    Sends an email using authenticated Gmail SMTP with a beautiful UI HTML template.
    """
    to_email, to_name = resolve_recipient(to)

    if not to_email or "@" not in to_email:
        err = f"Invalid recipient email address: '{to}'"
        _log_ui(f"❌ {err}", player)
        return {"success": False, "message": err, "recipient": to, "subject": subject}

    if not subject or not subject.strip():
        subject = "Message from Hammad Nawaz via AUREX"

    if not body or not body.strip():
        body = "Hello! This is a transmission sent via AUREX AI Assistant."

    user_email, app_password, default_sender = get_gmail_credentials()
    actual_sender = sender_name or default_sender

    _log_ui(f"📧 Preparing UI email ({theme}) for {to_name} <{to_email}>...", player)

    # Build MIME message
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{actual_sender} <{user_email}>"
    msg["To"] = f"{to_name} <{to_email}>" if to_name != to_email else to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="aurex.local")

    # Plain text alternative
    plain_text = build_plain_text(
        to_name=to_name,
        to_email=to_email,
        subject=subject,
        body=body,
        sender_name=actual_sender,
        sender_email=user_email,
    )
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))

    # Rich UI HTML alternative
    html_content = build_html_email(
        to_name=to_name,
        to_email=to_email,
        subject=subject,
        body=body,
        theme_key=theme,
        button_text=button_text,
        button_url=button_url,
        sender_name=actual_sender,
        sender_email=user_email,
    )
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Optional attachments
    if attachments:
        for file_path_str in attachments:
            try:
                p = Path(file_path_str)
                if p.exists() and p.is_file():
                    with open(p, "rb") as f:
                        part = MIMEApplication(f.read(), Name=p.name)
                    part["Content-Disposition"] = f'attachment; filename="{p.name}"'
                    msg.attach(part)
                    _log_ui(f"📎 Attached: {p.name}", player)
            except Exception as ex:
                _log_ui(f"⚠ Could not attach '{file_path_str}': {ex}", player)

    # Transmit via Gmail SMTP (SSL on port 465)
    try:
        _log_ui(f"🚀 Connecting to smtp.gmail.com:465 via SSL...", player)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=25) as server:
            server.login(user_email, app_password)
            server.sendmail(user_email, [to_email], msg.as_string())

        success_msg = f"Email successfully delivered to {to_name} ({to_email}) with subject '{subject}'."
        _log_ui(f"✅ {success_msg}", player)

        if player and hasattr(player, "show_content"):
            try:
                preview = (
                    f"TO: {to_name} <{to_email}>\n"
                    f"SUBJECT: {subject}\n"
                    f"THEME: {theme}\n"
                    f"STATUS: Delivered via SSL SMTP\n"
                    f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"--- MESSAGE CONTENT ---\n{body[:350]}"
                    f"{'...' if len(body) > 350 else ''}"
                )
                player.show_content("GMAIL DISPATCH", preview)
            except Exception:
                pass

        return {
            "success": True,
            "message": success_msg,
            "recipient": to_email,
            "subject": subject,
            "theme": theme
        }

    except smtplib.SMTPAuthenticationError as e:
        err = f"Gmail SMTP Authentication failed. Please verify the 16-character App Password. Error: {e}"
        _log_ui(f"❌ {err}", player)
        return {"success": False, "message": err, "recipient": to_email, "subject": subject}
    except Exception as e:
        err = f"Failed to send email to {to_email}: {e}"
        _log_ui(f"❌ {err}", player)
        return {"success": False, "message": err, "recipient": to_email, "subject": subject}


def _log_ui(msg: str, player=None):
    try:
        print(f"[AUREX Gmail] {msg}")
    except UnicodeEncodeError:
        safe_msg = msg.encode("ascii", errors="replace").decode("ascii")
        print(f"[AUREX Gmail] {safe_msg}")
    if player and hasattr(player, "write_log"):
        try:
            player.write_log(f"AUREX: {msg}")
        except Exception:
            pass


# ── AI NATURAL LANGUAGE PARSER ───────────────────────────────────────────────
def parse_natural_command(prompt: str) -> dict:
    """
    Parses a conversational command into structured email parameters:
    to, subject, body, theme.
    Uses Gemini API if available, or a fallback heuristic parser.
    """
    clean_prompt = prompt.strip()

    # Try Gemini via core.gemini or google.genai
    env_vars = load_env_vars()
    gemini_key = os.environ.get("GEMINI_API_KEY") or env_vars.get("GEMINI_API_KEY")
    if not gemini_key and API_KEYS_PATH.exists():
        try:
            gemini_key = json.loads(API_KEYS_PATH.read_text(encoding="utf-8")).get("gemini_api_key")
        except Exception:
            pass

    if gemini_key:
        try:
            from google import genai
            client = genai.Client(api_key=gemini_key)
            system_instruction = (
                "You are the email dispatch parser for AUREX AI Assistant. "
                "The user will give you a natural language instruction to send an email. "
                "Extract or compose: "
                "1. 'to': recipient email address or name (e.g. 'john@example.com' or 'hammad'). "
                "2. 'subject': an appropriate, professional, and punchy subject line. "
                "3. 'body': the email body content. If the user only gave a brief intention, write a polished, polite, and complete email body using markdown. "
                "4. 'theme': choose one of: 'cyber_aurex', 'aurora_purple', 'executive_modern', 'clean_light'. "
                "Return ONLY a valid JSON object with keys: to, subject, body, theme."
            )
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f"User command: {clean_prompt}",
                config={"system_instruction": system_instruction, "response_mime_type": "application/json"}
            )
            if response and response.text:
                data = json.loads(response.text.strip())
                if isinstance(data, dict) and data.get("to"):
                    return data
        except Exception as e:
            print(f"[AUREX Gmail] AI parsing fallback: {e}")

    # Heuristic Regex Fallback
    # Patterns like: "send email to <email> subject <subject> body <body>"
    # or "mail <recipient> that <body>"
    to = ""
    subject = "Message from Hammad"
    body = clean_prompt
    theme = "cyber_aurex"

    # Extract email or contact after "to"
    to_match = re.search(r"\bto\s+([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z0-9_]+)", clean_prompt, re.IGNORECASE)
    if to_match:
        to = to_match.group(1).strip()

    # Extract subject
    subj_match = re.search(r"\b(?:subject|regarding|about)\s+[\"']?([^\"'\n]+)[\"']?\s+(?:body|saying|that)", clean_prompt, re.IGNORECASE)
    if subj_match:
        subject = subj_match.group(1).strip()
    else:
        subj_match2 = re.search(r"\b(?:subject|regarding|about)\s+[\"']?([^\"'\n]+)[\"']?$", clean_prompt, re.IGNORECASE)
        if subj_match2:
            subject = subj_match2.group(1).strip()

    # Extract body after "saying" or "that" or "body"
    body_match = re.search(r"\b(?:saying|that|body|message)\s+(.+)$", clean_prompt, re.IGNORECASE)
    if body_match:
        body = body_match.group(1).strip()
    elif to:
        # Strip the "send email to X" prefix
        body = re.sub(r"^(?:aurex\s*,?\s*)?(?:send\s+)?(?:an\s+)?(?:email|mail)\s+to\s+\S+\s*", "", clean_prompt, flags=re.IGNORECASE).strip()

    return {
        "to": to or "hammadnawaz519@gmail.com",
        "subject": subject or "Transmission from AUREX",
        "body": body or "Hello! This is a test email sent from AUREX AI.",
        "theme": theme
    }


# ── AUREX ACTION REGISTRY INTEGRATION ─────────────────────────────────────────
def send_gmail_action(
    parameters: dict,
    player=None,
    session_memory=None,
    **kwargs
) -> str:
    """
    AUREX Action Handler for sending Gmail messages.
    Called when the user instructs AUREX by voice or live chat.
    """
    params = parameters or {}
    to = params.get("to", "").strip()
    subject = params.get("subject", "").strip()
    body = params.get("body", "").strip()
    theme = params.get("theme", "cyber_aurex").strip().lower()
    button_text = params.get("button_text")
    button_url = params.get("button_url")

    if not to:
        msg = "Sir, please specify who you would like me to send the email to."
        _log_ui(msg, player)
        return msg

    if not body:
        msg = f"Sir, what message would you like me to include in the email to {to}?"
        _log_ui(msg, player)
        return msg

    if not subject:
        subject = f"Message from Hammad Nawaz"

    if theme not in THEMES:
        theme = "cyber_aurex"

    result = send_email(
        to=to,
        subject=subject,
        body=body,
        theme=theme,
        button_text=button_text,
        button_url=button_url,
        player=player
    )

    if result.get("success"):
        spoken_response = f"Sir, I have dispatched your email to {to} with the subject '{subject}'. It has been delivered successfully."
    else:
        spoken_response = f"Sir, I encountered an issue sending the email to {to}: {result.get('message')}"

    return spoken_response


# TOOL declaration for AUREX action_loader (auto-discovered in actions/)
TOOL = {
    "name": "gmail",
    "description": (
        "Sends an email via Gmail using a beautiful, modern UI-styled HTML template. "
        "Use this whenever the user asks to send an email, mail someone, send a message through Gmail, "
        "compose an email, or notify someone via email. "
        "Supports recipient email or contact names, custom subjects, markdown-styled body, "
        "and UI themes ('cyber_aurex', 'executive_modern', 'aurora_purple', 'clean_light')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "to": {
                "type": "STRING",
                "description": "Recipient email address (e.g. 'john@example.com') or contact name (e.g. 'Dad', 'Hammad')"
            },
            "subject": {
                "type": "STRING",
                "description": "The subject line of the email"
            },
            "body": {
                "type": "STRING",
                "description": "Content of the email message. Supports markdown (bullet points, bold text, quotes, code)."
            },
            "theme": {
                "type": "STRING",
                "description": "Optional UI theme: 'cyber_aurex' (default dark neon), 'executive_modern', 'aurora_purple', or 'clean_light'"
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
        "required": ["to", "subject", "body"]
    },
    "handler": send_gmail_action
}


# ── STANDALONE CLI & INTERACTIVE CONSOLE ─────────────────────────────────────
def open_html_preview(to: str, subject: str, body: str, theme: str = "cyber_aurex"):
    """Renders HTML email to a temporary file and opens in default browser."""
    to_email, to_name = resolve_recipient(to)
    user_email, _, sender_name = get_gmail_credentials()
    html = build_html_email(
        to_name=to_name,
        to_email=to_email,
        subject=subject,
        body=body,
        theme_key=theme,
        sender_name=sender_name,
        sender_email=user_email
    )
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html", encoding="utf-8") as f:
        f.write(html)
        temp_path = f.name
    print(f"Opening preview in browser: {temp_path}")
    webbrowser.open(f"file://{temp_path}")


def interactive_console():
    user, _, name = get_gmail_credentials()
    print("=" * 66)
    print("      ⚡  A U R E X   G M A I L   S Y S T E M  ⚡")
    print("      Autonomous Beautiful UI Email Dispatcher")
    print(f"      Logged in as: {user} ({name})")
    print("=" * 66)
    print("\nAvailable Commands:")
    print("  1. 'send'       - Interactive step-by-step email composer")
    print("  2. 'test'       - Send an immediate test UI email to yourself")
    print("  3. 'preview'    - Preview the beautiful UI template in your browser")
    print("  4. 'say <text>' - Command AUREX with natural language (e.g. 'say email alex about meeting')")
    print("  5. 'contacts'   - View and manage your email address book")
    print("  6. 'exit'       - Quit the console\n")

    while True:
        try:
            cmd = input("\nAUREX >> ").strip()
            if not cmd:
                continue

            low = cmd.lower()
            if low in ("exit", "quit", "q"):
                print("AUREX Gmail Communicator standing down. Goodbye, sir.")
                break

            elif low == "test":
                print(f"\n⚡ Dispatching test UI email to {user}...")
                test_body = (
                    "## Welcome to AUREX Intelligent Dispatch\n\n"
                    "This is a demonstration of your **AUREX Beautiful UI Mail System**.\n\n"
                    "### System Capabilities:\n"
                    "- **Autonomous Transmission:** Just command AUREX by voice or text.\n"
                    "- **High-Tech Aesthetic:** Gorgeous glowing responsive dark UI cards.\n"
                    "- **Markdown Support:** Clean headers, bullet points, quotes, and buttons.\n"
                    "- **Instant Contact Resolution:** Saves and recalls your contacts.\n\n"
                    "> \"The future belongs to those who prepare for it today.\" — AUREX Core\n\n"
                    "Everything is configured and operational, sir!"
                )
                res = send_email(
                    to=user,
                    subject="⚡ AUREX Neural Transmission: Test Verification",
                    body=test_body,
                    theme="cyber_aurex",
                    button_text="AUREX Intelligence Core",
                    button_url="https://github.com"
                )
                print(f"Result: {res['message']}")

            elif low == "preview":
                open_html_preview(
                    to=user,
                    subject="⚡ AUREX UI Email Preview",
                    body="## Visual UI Verification\n\nHere is how your emails look to recipients!\n\n- Sleek neon styling\n- Crisp typography\n- Mobile responsive",
                    theme="cyber_aurex"
                )

            elif low == "contacts":
                contacts = load_contacts()
                print("\nSaved Contacts:")
                for k, v in contacts.items():
                    print(f"  • {k.title():<15} -> {v}")
                sub = input("\nAdd new contact? (y/n): ").strip().lower()
                if sub == "y":
                    cname = input("Contact Name: ").strip()
                    cemail = input("Contact Email: ").strip()
                    if cname and cemail:
                        save_contact(cname, cemail)
                        print(f"✅ Contact '{cname}' ({cemail}) saved successfully!")

            elif low == "send":
                print("\n--- COMPOSE AUREX UI EMAIL ---")
                to = input("Recipient (email or contact name): ").strip()
                if not to:
                    print("Cancelled: Recipient required.")
                    continue
                subject = input("Subject: ").strip()
                print("Enter message body (Markdown supported, type 'END' on a new line when finished):")
                lines = []
                while True:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)
                body = "\n".join(lines)

                print("\nSelect Theme:")
                print("1. cyber_aurex (Default Dark Neon)")
                print("2. executive_modern (Sleek Slate)")
                print("3. aurora_purple (Galactic Glow)")
                print("4. clean_light (Professional Light)")
                th_choice = input("Choice [1-4] (default: 1): ").strip()
                theme_map = {"1": "cyber_aurex", "2": "executive_modern", "3": "aurora_purple", "4": "clean_light"}
                theme = theme_map.get(th_choice, "cyber_aurex")

                confirm = input(f"\nSend this email to '{to}' now? (y/n/preview): ").strip().lower()
                if confirm == "preview":
                    open_html_preview(to, subject, body, theme)
                    confirm = input("Send now? (y/n): ").strip().lower()

                if confirm == "y":
                    res = send_email(to, subject, body, theme=theme)
                    print(f"Result: {res['message']}")
                else:
                    print("Transmission cancelled.")

            elif low.startswith("say ") or low.startswith("command "):
                instruction = cmd.split(" ", 1)[1]
                print(f"Processing command: \"{instruction}\"...")
                parsed = parse_natural_command(instruction)
                print(f"\n[AI Parsed Plan]")
                print(f"  To:      {parsed.get('to')}")
                print(f"  Subject: {parsed.get('subject')}")
                print(f"  Theme:   {parsed.get('theme')}")
                print(f"  Body Preview: {parsed.get('body')[:120]}...")

                conf = input("\nAuthorize AUREX to send? (y/n): ").strip().lower()
                if conf == "y":
                    res = send_email(
                        to=parsed["to"],
                        subject=parsed["subject"],
                        body=parsed["body"],
                        theme=parsed.get("theme", "cyber_aurex")
                    )
                    print(f"Result: {res['message']}")
                else:
                    print("Cancelled.")

            else:
                # Treat any free text as a natural language command!
                print(f"Processing: \"{cmd}\"...")
                parsed = parse_natural_command(cmd)
                print(f"\n[AI Parsed Plan]")
                print(f"  To:      {parsed.get('to')}")
                print(f"  Subject: {parsed.get('subject')}")
                print(f"  Theme:   {parsed.get('theme')}")
                print(f"  Body:    \n{parsed.get('body')}")

                conf = input("\nAuthorize AUREX to send? (y/n): ").strip().lower()
                if conf == "y":
                    res = send_email(
                        to=parsed["to"],
                        subject=parsed["subject"],
                        body=parsed["body"],
                        theme=parsed.get("theme", "cyber_aurex")
                    )
                    print(f"Result: {res['message']}")
                else:
                    print("Cancelled.")

        except KeyboardInterrupt:
            print("\nExiting AUREX...")
            break
        except Exception as e:
            print(f"Error: {e}")


def main():
    parser = argparse.ArgumentParser(description="AUREX Gmail Communicator - Autonomous UI Email System")
    parser.add_argument("--to", help="Recipient email address or contact name")
    parser.add_argument("--subject", help="Subject of the email")
    parser.add_argument("--body", help="Message body text (supports markdown)")
    parser.add_argument("--theme", choices=list(THEMES.keys()), default="cyber_aurex", help="Email UI theme")
    parser.add_argument("--button-text", help="Text for call to action button")
    parser.add_argument("--button-url", help="URL for call to action button")
    parser.add_argument("--attach", nargs="*", help="File paths to attach")
    parser.add_argument("--command", help="Natural language instruction for AUREX (e.g. 'send email to x saying y')")
    parser.add_argument("--test", action="store_true", help="Send a test UI email to verify the setup")
    parser.add_argument("--preview", action="store_true", help="Open a preview of the UI email in browser")
    parser.add_argument("--add-contact", nargs=2, metavar=("NAME", "EMAIL"), help="Add a contact: --add-contact Ali ali@example.com")
    parser.add_argument("--list-contacts", action="store_true", help="List all saved contacts")

    args = parser.parse_args()

    if args.add_contact:
        save_contact(args.add_contact[0], args.add_contact[1])
        print(f"✅ Saved contact: {args.add_contact[0]} -> {args.add_contact[1]}")
        return

    if args.list_contacts:
        contacts = load_contacts()
        print("AUREX Address Book:")
        for k, v in contacts.items():
            print(f"  • {k.title():<15} -> {v}")
        return

    if args.test:
        user, _, _ = get_gmail_credentials()
        print(f"Sending test UI email to {user}...")
        test_body = (
            "## AUREX Dispatch Verification\n\n"
            "This test email confirms that your **AUREX Gmail System** is fully operational!\n\n"
            "### Features Activated:\n"
            "- **Google SMTP Relay:** Authenticated with App Password\n"
            "- **Responsive UI Design:** Formatted with Cyber Aurex Dark Theme\n"
            "- **AUREX Voice/Chat Integration:** Say *'Aurex, send an email to...'* anytime!"
        )
        res = send_email(
            to=user,
            subject="⚡ AUREX Neural Verification Test",
            body=test_body,
            theme=args.theme or "cyber_aurex",
            button_text="AUREX Intelligence",
            button_url="https://google.com"
        )
        print(res["message"])
        return

    if args.preview:
        to = args.to or DEFAULT_GMAIL_USER
        subj = args.subject or "⚡ AUREX Email Preview"
        body = args.body or "## AUREX Interface Preview\n\nThis is a preview of the rendered email layout."
        open_html_preview(to, subj, body, theme=args.theme or "cyber_aurex")
        return

    if args.command:
        parsed = parse_natural_command(args.command)
        print(f"Executing natural language instruction for recipient: {parsed.get('to')}...")
        res = send_email(
            to=parsed["to"],
            subject=parsed["subject"],
            body=parsed["body"],
            theme=parsed.get("theme", args.theme or "cyber_aurex")
        )
        print(res["message"])
        return

    if args.to and (args.body or args.subject):
        res = send_email(
            to=args.to,
            subject=args.subject or "Message from Hammad",
            body=args.body or "",
            theme=args.theme,
            button_text=args.button_text,
            button_url=args.button_url,
            attachments=args.attach
        )
        print(res["message"])
        return

    # If no arguments provided, launch interactive console
    interactive_console()


if __name__ == "__main__":
    main()
