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
    """Resolves contact alias or raw email address."""
    raw = recipient_input.strip()
    email_match = re.search(r"<([^>]+)>", raw)
    if email_match:
        email = email_match.group(1).strip()
        name = raw.split("<")[0].strip().strip('"').strip("'")
        return email, name or email

    if "@" in raw and "." in raw:
        return raw.lower(), raw.split("@")[0].title()

    contacts = load_contacts()
    normalized = raw.lower().replace(" ", "_")
    if normalized in contacts:
        return contacts[normalized], raw.title()

    for k, v in contacts.items():
        if k in normalized or normalized in k:
            return v, k.replace("_", " ").title()

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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            color: {theme['body_text']};
        }}
    </style>
</head>
<body style="margin: 0; padding: 30px 10px; background-color: {theme['body_bg']};">
    <center>
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
                        
                        <!-- META ROW -->
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
    theme: str = "cyber_aurex",
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

        if player and hasattr(player, "show_content"):
            try:
                preview = (
                    f"TO: {to_name} <{to_email}>\n"
                    f"SUBJECT: {subject}\n"
                    f"THEME: {theme}\n"
                    f"STATUS: Delivered via SSL SMTP\n"
                    f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"--- MESSAGE BODY ---\n{body[:350]}"
                    f"{'...' if len(body) > 350 else ''}"
                )
                player.show_content("GMAIL DISPATCH", preview)
            except Exception:
                pass

        return True, f"Email delivered to {to_name} ({to_email}) with subject '{subject}'."

    except smtplib.SMTPAuthenticationError as e:
        err = f"Gmail SMTP Authentication failed. Please verify the 16-character App Password. Error: {e}"
        _log_player(f"❌ {err}", player)
        return False, err
    except Exception as e:
        err = f"Failed to send email to {to_email}: {e}"
        _log_player(f"❌ {err}", player)
        return False, err


# ── PLUGIN REGISTRATION & ENTRYPOINT ─────────────────────────────────────────

PLUGIN = {
    "name": "gmail",
    "description": (
        "Sends an email via Gmail using a beautiful, modern UI-styled HTML template. "
        "Use this tool whenever the user asks to send an email, mail someone, send a message through Gmail, "
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
    to = params.get("to", "").strip()
    subject = params.get("subject", "").strip()
    body = params.get("body", "").strip()
    theme = params.get("theme", "cyber_aurex").strip().lower()
    button_text = params.get("button_text")
    button_url = params.get("button_url")

    if not to:
        return "Sir, please specify who you would like me to send the email to."

    if not body:
        return f"Sir, what message would you like me to include in the email to {to}?"

    if not subject:
        subject = "Message from Hammad Nawaz"

    if theme not in THEMES:
        theme = "cyber_aurex"

    ok, msg = send_email(
        to=to,
        subject=subject,
        body=body,
        theme=theme,
        button_text=button_text,
        button_url=button_url,
        player=player
    )

    if ok:
        return f"Sir, I have dispatched your email to {to} with the subject '{subject}'. It has been delivered successfully."
    else:
        return f"Sir, I encountered an issue sending the email to {to}: {msg}"
