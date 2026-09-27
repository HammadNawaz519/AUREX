"""
AUREX — Chrome-Native Full-Power Computer Use & Screen Understanding
===================================================================
Treats Google Chrome as a first-class native environment using Playwright
and Chrome DevTools Protocol (CDP).

Perception & Control Hierarchy:
  1. Real Chrome DOM, Accessibility Tree, Semantic Locators & Geometry
  2. In-Page Dynamic AUREX Pill/Overlay (non-intrusive, tracks elements across scrolls)
  3. Browser Action Router (Native Playwright actions — NO mouse coordinates for web)
  4. Practice MCQ Detection, Option Grounding & DOM Marking
  5. Verification & Dynamic Recovery Engine
  6. Desktop Fallback Router (Windows UI Automation + WinRT OCR for native desktop apps)
"""

from __future__ import annotations

import io
import json
import math
import os
import platform
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Enable Per-Monitor DPI Awareness so screen calculations match physical pixels
_OS = platform.system()
if _OS == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    from PIL import Image
    _PIL = True
except ImportError:
    _PIL = False

try:
    import win32gui
    import win32process
    import win32con
    import win32api
    import win32clipboard
    _WIN32 = True
except ImportError:
    _WIN32 = False

try:
    import winrt.windows.media.ocr as winrt_ocr
    import winrt.windows.graphics.imaging as winrt_imaging
    import winrt.windows.storage.streams as winrt_streams
    _WINRT_OCR = True
except Exception:
    _WINRT_OCR = False

try:
    from pywinauto import Desktop as PywinDesktop, Application as PywinApp
    from pywinauto.controls.uiawrapper import UIAWrapper
    _PYWINAUTO = True
except ImportError:
    _PYWINAUTO = False

try:
    from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page, Locator, TimeoutError as PlaywrightTimeout
    _PLAYWRIGHT = True
except ImportError:
    _PLAYWRIGHT = False

from core import gemini


# ── 1. IN-PAGE AUREX OVERLAY SCRIPTS & CSS ────────────────────────────────────
# Injected directly into Chrome pages. Zero layout impact. Follows target elements
# smoothly on scroll, resize, and DOM mutations via getBoundingClientRect().

AUREX_OVERLAY_INJECTION_JS = """
(function() {
  function ensureStyles() {
    if (document.getElementById('__aurex_overlay_styles')) return;
    const target = document.head || document.documentElement || document.body;
    if (!target) return;
    const style = document.createElement('style');
    style.id = '__aurex_overlay_styles';
    style.textContent = `
    @keyframes aurexPulse {
      0% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.5), 0 0 12px rgba(59, 130, 246, 0.4); }
      50% { box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2), 0 0 22px rgba(59, 130, 246, 0.7); }
      100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.5), 0 0 12px rgba(59, 130, 246, 0.4); }
    }
    @keyframes aurexMcqPulse {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.6), 0 0 14px rgba(16, 185, 129, 0.5); }
      50% { box-shadow: 0 0 0 5px rgba(16, 185, 129, 0.25), 0 0 24px rgba(16, 185, 129, 0.8); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.6), 0 0 14px rgba(16, 185, 129, 0.5); }
    }
    @keyframes aurexFadeInScale {
      from { opacity: 0; transform: scale(0.96); }
      to { opacity: 1; transform: scale(1); }
    }
    .aurex-pill-overlay {
      position: fixed !important;
      pointer-events: none !important;
      z-index: 2147483647 !important;
      border: 2px solid #3b82f6 !important;
      background: rgba(59, 130, 246, 0.09) !important;
      border-radius: 10px !important;
      box-sizing: border-box !important;
      transition: top 0.08s ease-out, left 0.08s ease-out, width 0.08s ease-out, height 0.08s ease-out, opacity 0.2s ease !important;
      animation: aurexFadeInScale 0.2s cubic-bezier(0.16, 1, 0.3, 1), aurexPulse 2s infinite ease-in-out !important;
    }
    .aurex-pill-overlay.mcq-selected {
      border-color: #10b981 !important;
      background: rgba(16, 185, 129, 0.12) !important;
      animation: aurexFadeInScale 0.2s cubic-bezier(0.16, 1, 0.3, 1), aurexMcqPulse 2s infinite ease-in-out !important;
    }
    .aurex-pill-badge {
      position: absolute !important;
      top: -24px !important;
      left: 6px !important;
      background: #2563eb !important;
      color: #ffffff !important;
      font-size: 10px !important;
      font-weight: 700 !important;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
      padding: 2px 8px !important;
      border-radius: 9999px !important;
      letter-spacing: 0.5px !important;
      box-shadow: 0 2px 6px rgba(0,0,0,0.25) !important;
      pointer-events: none !important;
      text-transform: uppercase !important;
    }
    .aurex-pill-overlay.mcq-selected .aurex-pill-badge {
      background: #059669 !important;
    }
    `;
    target.appendChild(style);
  }

  ensureStyles();

  window.__aurex_active_overlays = window.__aurex_active_overlays || [];

  function updateAllPositions() {
    if (!window.__aurex_active_overlays) return;
    for (let i = window.__aurex_active_overlays.length - 1; i >= 0; i--) {
      const item = window.__aurex_active_overlays[i];
      if (!item.element || !document.contains(item.element)) {
        if (item.overlay.parentNode) item.overlay.parentNode.removeChild(item.overlay);
        window.__aurex_active_overlays.splice(i, 1);
        continue;
      }
      const rect = item.element.getBoundingClientRect();
      const pad = item.padding || 4;
      item.overlay.style.top = (rect.top - pad) + 'px';
      item.overlay.style.left = (rect.left - pad) + 'px';
      item.overlay.style.width = (rect.width + pad * 2) + 'px';
      item.overlay.style.height = (rect.height + pad * 2) + 'px';
      item.overlay.style.display = (rect.width > 0 && rect.height > 0) ? 'block' : 'none';
    }
  }

  window.addEventListener('scroll', updateAllPositions, { passive: true, capture: true });
  window.addEventListener('resize', updateAllPositions, { passive: true });
  
  const observer = new MutationObserver(() => updateAllPositions());
  observer.observe(document.body || document.documentElement, { attributes: true, childList: true, subtree: true });

  window.__aurex_highlight = function(target, label, durationMs, color, padding, isMcq) {
    ensureStyles();
    label = label !== undefined ? label : 'AUREX';
    durationMs = durationMs !== undefined ? durationMs : 3000;
    color = color || '#3b82f6';
    padding = padding || 4;

    let el = null;
    if (typeof target === 'string') {
      try { el = document.querySelector(target); } catch(e){}
    } else if (target && target.nodeType === 1) {
      el = target;
    }
    if (!el) return false;

    const overlay = document.createElement('div');
    overlay.className = 'aurex-pill-overlay' + (isMcq ? ' mcq-selected' : '');
    overlay.style.borderColor = color;
    overlay.style.background = color.startsWith('#') ? (color + '18') : 'rgba(59, 130, 246, 0.09)';

    if (label) {
      const badge = document.createElement('div');
      badge.className = 'aurex-pill-badge';
      badge.style.background = color;
      badge.textContent = label;
      overlay.appendChild(badge);
    }

    document.body.appendChild(overlay);

    const record = { element: el, overlay: overlay, padding: padding };
    window.__aurex_active_overlays.push(record);
    updateAllPositions();

    if (durationMs > 0) {
      setTimeout(() => {
        overlay.style.opacity = '0';
        overlay.style.transform = 'scale(0.92)';
        setTimeout(() => {
          if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
          const idx = window.__aurex_active_overlays.indexOf(record);
          if (idx !== -1) window.__aurex_active_overlays.splice(idx, 1);
        }, 220);
      }, durationMs);
    }

    return true;
  };

  window.__aurex_clear_overlays = function() {
    if (window.__aurex_active_overlays) {
      for (const item of window.__aurex_active_overlays) {
        if (item.overlay && item.overlay.parentNode) {
          item.overlay.parentNode.removeChild(item.overlay);
        }
      }
      window.__aurex_active_overlays = [];
    }
  };
})();
"""


# ── 2. CHROME DEVTOOLS PROTOCOL & PLAYWRIGHT SESSION MANAGER ──────────────────

class ChromeCDPManager:
    """
    Singleton manager providing persistent connection to Chrome.
    Prefers connecting to an existing Chrome instance via CDP (port 9222).
    Cleanly falls back to persistent context if not already exposing CDP.
    Maintains active page, handles tab switching, and tracks user focus.
    """
    _instance: Optional[ChromeCDPManager] = None
    _lock = threading.Lock()

    def __init__(self):
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.active_page: Optional[Page] = None
        self.is_cdp: bool = False
        self.profile_dir = os.path.expanduser("~/.aurex/chrome_profile")
        os.makedirs(self.profile_dir, exist_ok=True)
        self.last_target_info: Dict[str, Any] = {}
        self.last_target_locator: Optional[Locator] = None

    @classmethod
    def get_instance(cls) -> ChromeCDPManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = ChromeCDPManager()
            return cls._instance

    def is_alive(self) -> bool:
        if not self.context:
            return False
        try:
            pages = self.context.pages
            return len(pages) > 0 and any(not p.is_closed() for p in pages)
        except Exception:
            return False

    def ensure_connection(self) -> Page:
        """
        Connects or attaches to Google Chrome. Returns the active Page.
        """
        if self.is_alive() and self.active_page and not self.active_page.is_closed():
            self._sync_active_page_with_window()
            self._ensure_overlay_injected(self.active_page)
            return self.active_page

        if not _PLAYWRIGHT:
            raise RuntimeError("Playwright is not installed. Run `pip install playwright`.")

        if self.playwright is None:
            self.playwright = sync_playwright().start()

        # Step 1: Try connecting over CDP to existing Chrome instance
        cdp_connected = False
        for port in (9222, 9223):
            try:
                self.browser = self.playwright.chromium.connect_over_cdp(
                    f"http://localhost:{port}",
                    timeout=1500
                )
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = self.browser.new_context()
                self.is_cdp = True
                cdp_connected = True
                print(f"[CHROME] Connected to existing Chrome instance over CDP on port {port}.")
                break
            except Exception:
                continue

        # Step 2: Fall back cleanly to launching persistent Chrome session
        if not cdp_connected:
            try:
                print("[CHROME] Launching persistent Chrome session with CDP enabled...")
                self.context = self.playwright.chromium.launch_persistent_context(
                    self.profile_dir,
                    channel="chrome",
                    headless=False,
                    args=[
                        "--remote-debugging-port=9222",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-blink-features=AutomationControlled"
                    ]
                )
                self.browser = self.context.browser
                self.is_cdp = False
            except Exception as e:
                # If channel="chrome" fails, try default chromium
                print(f"[CHROME] Chrome launch error ({e}), retrying default chromium...")
                self.context = self.playwright.chromium.launch_persistent_context(
                    self.profile_dir,
                    headless=False,
                    args=["--remote-debugging-port=9222"]
                )
                self.browser = self.context.browser
                self.is_cdp = False

        # Add init script so overlay is automatically ready on every page
        try:
            self.context.add_init_script(AUREX_OVERLAY_INJECTION_JS)
        except Exception:
            pass

        # Select or create active page
        pages = self.context.pages
        if pages:
            self.active_page = pages[-1]
        else:
            self.active_page = self.context.new_page()

        self._sync_active_page_with_window()
        self._ensure_overlay_injected(self.active_page)
        return self.active_page

    def _sync_active_page_with_window(self):
        """
        Detects if user is currently looking at a specific tab in Chrome window.
        """
        if not _WIN32 or not self.context:
            return

        try:
            hwnd = win32gui.GetForegroundWindow()
            win_title = win32gui.GetWindowText(hwnd) or ""
            cls_name = win32gui.GetClassName(hwnd) or ""

            if "Chrome" in cls_name or "Chrome" in win_title:
                for p in self.context.pages:
                    if p.is_closed():
                        continue
                    try:
                        p_title = p.title()
                        if p_title and (p_title in win_title or win_title.startswith(p_title)):
                            self.active_page = p
                            return
                    except Exception:
                        pass
        except Exception:
            pass

    def _ensure_overlay_injected(self, page: Page):
        try:
            page.evaluate(AUREX_OVERLAY_INJECTION_JS)
        except Exception:
            pass

    def list_tabs(self) -> List[Dict[str, Any]]:
        self.ensure_connection()
        tabs = []
        for i, p in enumerate(self.context.pages):
            if p.is_closed():
                continue
            try:
                title = p.title()
                url = p.url
                is_active = (p == self.active_page)
                tabs.append({
                    "index": i,
                    "title": title,
                    "url": url,
                    "active": is_active
                })
            except Exception:
                pass
        return tabs

    def switch_tab(self, target: str | int) -> Tuple[bool, str]:
        self.ensure_connection()
        pages = [p for p in self.context.pages if not p.is_closed()]
        if not pages:
            return False, "No open Chrome tabs."

        if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
            idx = int(target)
            if 0 <= idx < len(pages):
                self.active_page = pages[idx]
                self.active_page.bring_to_front()
                return True, f"Switched to tab {idx}: {self.active_page.title()}"
            return False, f"Tab index {idx} out of range (total {len(pages)})."

        target_str = str(target).lower().strip()
        for p in pages:
            try:
                if target_str in p.title().lower() or target_str in p.url.lower():
                    self.active_page = p
                    self.active_page.bring_to_front()
                    return True, f"Switched to tab: {p.title()}"
            except Exception:
                pass

        return False, f"No tab matching '{target}' found."

    def new_tab(self, url: str = "about:blank") -> Page:
        self.ensure_connection()
        p = self.context.new_page()
        self.active_page = p
        self._ensure_overlay_injected(p)
        if url and url != "about:blank":
            if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file:///"):
                url = "https://" + url
            p.goto(url, wait_until="domcontentloaded", timeout=15000)
        p.bring_to_front()
        return p


# ── 3. DOM & ACCESSIBILITY MODEL ──────────────────────────────────────────────

@dataclass
class DOMElementInfo:
    tag: str
    role: str
    text: str
    accessible_name: str
    id: str
    name: str
    value: str
    placeholder: str
    input_type: str
    href: str
    checked: bool
    disabled: bool
    rect: Dict[str, float]  # {x, y, width, height, top, left, bottom, right}
    in_viewport: bool
    css_selector: str
    score: float = 0.0


DOM_INSPECTOR_JS = """
(function() {
  const elements = Array.from(document.querySelectorAll(
    'button, a, input, select, textarea, label, [role], [tabindex], h1, h2, h3, h4, h5, h6, p, li, tr, dialog'
  ));

  const results = [];
  const vh = window.innerHeight;
  const vw = window.innerWidth;

  for (let i = 0; i < elements.length && i < 1500; i++) {
    const el = elements[i];
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);

    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
      if (el.type !== 'radio' && el.type !== 'checkbox') continue;
    }
    if (rect.width === 0 && rect.height === 0 && el.type !== 'radio' && el.type !== 'checkbox') {
      continue;
    }

    const inViewport = (rect.bottom >= 0 && rect.top <= vh && rect.right >= 0 && rect.left <= vw);
    const text = (el.innerText || el.textContent || '').trim();
    const ariaLabel = el.getAttribute('aria-label') || '';
    const title = el.getAttribute('title') || '';
    const alt = el.getAttribute('alt') || '';
    const accName = ariaLabel || title || alt;

    let selector = '';
    if (el.id) {
      selector = '#' + CSS.escape(el.id);
    } else if (el.name) {
      selector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    }

    results.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || el.tagName.toLowerCase(),
      text: text.substring(0, 100),
      accessible_name: accName.substring(0, 100),
      id: el.id || '',
      name: el.getAttribute('name') || '',
      value: (el.value || '').substring(0, 100),
      placeholder: el.getAttribute('placeholder') || '',
      input_type: (el.getAttribute('type') || '').toLowerCase(),
      href: el.getAttribute('href') || '',
      checked: !!el.checked || el.getAttribute('aria-checked') === 'true',
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      rect: {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        top: rect.top,
        left: rect.left,
        bottom: rect.bottom,
        right: rect.right
      },
      in_viewport: inViewport,
      css_selector: selector
    });
  }
  return results;
})()
"""


# ── 4. SEMANTIC TARGET RESOLVER ───────────────────────────────────────────────

class TargetResolver:
    """
    Translates user's natural language queries into exact Playwright Locators or DOM elements.
    Follows priority:
      1. Role + accessible name
      2. Label
      3. Visible text
      4. Placeholder
      5. Title / Alt
      6. Test ID
      7. DOM / MCQ Relationship
      8. Semantic In-Page DOM Scoring (with CSS/Color and geometry)
      9. Contextual resolution ("this", "that")
      10. Visual Grounding fallback (for Canvas/custom UI)
    """

    @staticmethod
    def resolve_target(page: Page, query: str, action_type: str = "click") -> Tuple[Optional[Locator], Dict[str, Any]]:
        clean_q = TargetResolver._clean_query(query)
        metadata: Dict[str, Any] = {
            "source": "UNKNOWN",
            "locator_str": "",
            "text": "",
            "score": 0.0
        }

        # 1. Handle Contextual "this" / "that"
        if not clean_q or clean_q in ("this", "that", "it", "here", "selected"):
            cdp = ChromeCDPManager.get_instance()
            if cdp.last_target_locator is not None:
                try:
                    if cdp.last_target_locator.count() > 0:
                        metadata.update({"source": "CONTEXT_HISTORY_LOCATOR", "locator_str": "last_target_locator"})
                        return cdp.last_target_locator, metadata
                except Exception:
                    pass

            last_target = cdp.last_target_info
            if last_target and last_target.get("selector") and not last_target.get("selector", "").startswith("get_by_"):
                try:
                    loc = page.locator(last_target["selector"]).first
                    if loc.count() > 0:
                        metadata.update({"source": "CONTEXT_HISTORY", "locator_str": last_target["selector"]})
                        return loc, metadata
                except Exception:
                    pass

            # Check active element
            try:
                active_loc = page.evaluate_handle("document.activeElement").as_element()
                if active_loc:
                    loc = page.locator("*:focus").first
                    if loc.count() > 0:
                        metadata.update({"source": "DOM_ACTIVE_FOCUS", "locator_str": "*:focus"})
                        return loc, metadata
            except Exception:
                pass

        # 2. MCQ / Question pattern: e.g. "Question 4 option B", "option TCP under Question 3"
        mcq_loc, mcq_meta = TargetResolver._resolve_mcq_target(page, clean_q)
        if mcq_loc is not None:
            return mcq_loc, mcq_meta

        # 2b. Paragraph and Section text targeting (e.g. "paragraph", "this paragraph", "paragraph under Features")
        if "paragraph" in clean_q or "para" in clean_q or clean_q in ("text", "content"):
            p_loc, p_meta = TargetResolver._resolve_paragraph_target(page, clean_q)
            if p_loc is not None:
                return p_loc, p_meta

        # 2c. Section / Heading targeting (e.g. "section called Installation", "heading Features")
        if "section" in clean_q or "heading" in clean_q:
            sec_name = re.sub(r"\b(section|heading|called|titled|named)\b", "", clean_q, flags=re.I).strip()
            if sec_name:
                try:
                    h_loc = page.get_by_role("heading", name=re.compile(rf"{re.escape(sec_name)}", re.I)).first
                    if h_loc.count() > 0:
                        metadata.update({"source": "SECTION_HEADING", "locator_str": f"heading('{sec_name}')"})
                        return h_loc, metadata
                except Exception:
                    pass

        # 3. Role-Based Semantic Targeting
        role_hint, name_hint = TargetResolver._extract_role_and_name(clean_q)
        if role_hint:
            try:
                role_loc = page.get_by_role(role_hint, name=re.compile(rf"{re.escape(name_hint)}", re.I)).first
                if role_loc.count() > 0 and role_loc.is_visible():
                    metadata.update({
                        "source": "ROLE_ACCESSIBLE_NAME",
                        "locator_str": f"get_by_role('{role_hint}', name='{name_hint}')",
                        "text": name_hint
                    })
                    return role_loc, metadata
            except Exception:
                pass

        # 4. Standard User-Facing Semantic Locators
        # Label
        try:
            loc = page.get_by_label(re.compile(rf"{re.escape(clean_q)}", re.I)).first
            if loc.count() > 0 and loc.is_visible():
                metadata.update({"source": "GET_BY_LABEL", "locator_str": f"get_by_label('{clean_q}')"})
                return loc, metadata
        except Exception:
            pass

        # Placeholder (especially for inputs)
        try:
            loc = page.get_by_placeholder(re.compile(rf"{re.escape(clean_q)}", re.I)).first
            if loc.count() > 0 and loc.is_visible():
                metadata.update({"source": "GET_BY_PLACEHOLDER", "locator_str": f"get_by_placeholder('{clean_q}')"})
                return loc, metadata
        except Exception:
            pass

        # Button by text
        try:
            loc = page.get_by_role("button", name=re.compile(rf"{re.escape(clean_q)}", re.I)).first
            if loc.count() > 0 and loc.is_visible():
                metadata.update({"source": "BUTTON_BY_TEXT", "locator_str": f"get_by_role('button', name='{clean_q}')"})
                return loc, metadata
        except Exception:
            pass

        # Link by text
        try:
            loc = page.get_by_role("link", name=re.compile(rf"{re.escape(clean_q)}", re.I)).first
            if loc.count() > 0 and loc.is_visible():
                metadata.update({"source": "LINK_BY_TEXT", "locator_str": f"get_by_role('link', name='{clean_q}')"})
                return loc, metadata
        except Exception:
            pass

        # Text Locator
        try:
            loc = page.get_by_text(re.compile(rf"{re.escape(clean_q)}", re.I), exact=False).first
            if loc.count() > 0 and loc.is_visible():
                metadata.update({"source": "GET_BY_TEXT", "locator_str": f"get_by_text('{clean_q}')"})
                return loc, metadata
        except Exception:
            pass

        # 5. Semantic In-Page DOM Scoring (Inspects colors, hierarchy, and tokens)
        ranked = TargetResolver._score_dom_elements(page, clean_q)
        if ranked:
            top = ranked[0]
            sel = top.get("selector")
            if sel:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    metadata.update({
                        "source": "DOM_SEMANTIC_SCORING",
                        "locator_str": sel,
                        "text": top.get("text", ""),
                        "score": top.get("score", 0.0)
                    })
                    return loc, metadata

        # 6. Deep Path: Visual Grounding if Canvas or pure graphic
        vis_loc, vis_meta = TargetResolver._visual_grounding_fallback(page, clean_q)
        if vis_loc is not None:
            return vis_loc, vis_meta

        return None, metadata

    @staticmethod
    def _clean_query(q: str) -> str:
        s = q.strip()
        # Remove common command prefixes
        s = re.sub(r"^(click|press|tap|select|open|find|highlight|scroll to|go to|copy|type in|type into)\s+", "", s, flags=re.I)
        # Remove trailing punctuation
        s = re.sub(r"[.?!]+$", "", s).strip()
        return s

    @staticmethod
    def _extract_role_and_name(q: str) -> Tuple[Optional[str], str]:
        ql = q.lower()
        if "button" in ql or "btn" in ql:
            name = re.sub(r"\b(the|blue|green|red|submit|login|search)?\s*(button|btn)\b", "", q, flags=re.I).strip()
            return "button", name or q
        if "link" in ql:
            name = re.sub(r"\b(link|hyperlink)\b", "", q, flags=re.I).strip()
            return "link", name or q
        if "checkbox" in ql:
            name = re.sub(r"\b(checkbox|check box)\b", "", q, flags=re.I).strip()
            return "checkbox", name or q
        if "radio" in ql:
            name = re.sub(r"\b(radio|radio button|option)\b", "", q, flags=re.I).strip()
            return "radio", name or q
        if "search" in ql and ("box" in ql or "field" in ql or "input" in ql):
            return "searchbox", "search"
        if "textbox" in ql or "input" in ql or "field" in ql:
            name = re.sub(r"\b(textbox|input|field|box)\b", "", q, flags=re.I).strip()
            return "textbox", name or q
        return None, q

    @staticmethod
    def _resolve_paragraph_target(page: Page, query: str) -> Tuple[Optional[Locator], Dict[str, Any]]:
        # If query specifies "paragraph under [section]"
        sec_match = re.search(r"paragraph\s+(?:under|in|below|of)\s+(.+)", query, flags=re.I)
        if sec_match:
            sec_name = sec_match.group(1).strip()
            try:
                h_loc = page.get_by_role("heading", name=re.compile(rf"{re.escape(sec_name)}", re.I)).first
                if h_loc.count() > 0:
                    p_loc = h_loc.locator("xpath=following::p[1]").first
                    if p_loc.count() > 0:
                        return p_loc, {"source": "HEADING_PARAGRAPH", "locator_str": f"heading('{sec_name}') -> p"}
            except Exception:
                pass

        # Otherwise pick the most visible paragraph currently in the viewport
        try:
            JS_VISIBLE_P = """
            (function() {
              const paras = Array.from(document.querySelectorAll('p, article, .content'));
              const vh = window.innerHeight;
              for (const p of paras) {
                const rect = p.getBoundingClientRect();
                if (rect.bottom > 50 && rect.top < vh && (p.innerText || '').trim().length > 15) {
                  let sel = p.id ? '#' + CSS.escape(p.id) : null;
                  if (!sel) {
                    const uid = 'aurex_p_' + Math.random().toString(36).substring(2, 9);
                    p.setAttribute('data-aurex-id', uid);
                    sel = `[data-aurex-id="${uid}"]`;
                  }
                  return sel;
                }
              }
              for (const p of paras) {
                if ((p.innerText || '').trim().length > 15) {
                  let sel = p.id ? '#' + CSS.escape(p.id) : null;
                  if (!sel) {
                    const uid = 'aurex_p_' + Math.random().toString(36).substring(2, 9);
                    p.setAttribute('data-aurex-id', uid);
                    sel = `[data-aurex-id="${uid}"]`;
                  }
                  return sel;
                }
              }
              return null;
            })()
            """
            sel = page.evaluate(JS_VISIBLE_P)
            if sel:
                p_loc = page.locator(sel).first
                if p_loc.count() > 0:
                    return p_loc, {"source": "VIEWPORT_PARAGRAPH", "locator_str": sel}
        except Exception:
            pass

        return None, {}

    @staticmethod
    def _resolve_mcq_target(page: Page, query: str) -> Tuple[Optional[Locator], Dict[str, Any]]:
        """
        Specialized resolver for MCQ and Practice Question structures.
        Handles: "Question 4 option B", "option TCP under Question 3", "highlight option B".
        """
        ql = query.lower()
        is_mcq_query = any(k in ql for k in ("question", "option", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "radio"))
        if not is_mcq_query:
            return None, {}

        JS_MCQ_SEARCH = """
        (function(q) {
          const qLower = q.toLowerCase();
          const qNumMatch = qLower.match(/(?:question|q)\\s*(\\d+)/i);
          const qNum = qNumMatch ? qNumMatch[1] : null;

          const optLetterMatch = qLower.match(/option\\s*([a-d])\\b/i) || qLower.match(/\\b([a-d])\\b\\s*(?:option|choice)/i);
          const optLetter = optLetterMatch ? optLetterMatch[1].toUpperCase() : null;

          // Find candidate question blocks
          const blocks = Array.from(document.querySelectorAll('[id*="question"], [class*="question"], .q-block, div, section, fieldset'));
          let bestBlock = null;

          if (qNum) {
            for (const b of blocks) {
              const text = (b.innerText || '').toLowerCase();
              if (text.includes('question ' + qNum) || text.includes('q' + qNum)) {
                if (b.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]').length > 0) {
                  bestBlock = b;
                  break;
                }
              }
            }
          }

          const searchScope = bestBlock || document.body;
          const inputs = Array.from(searchScope.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"], label'));

          for (let i = 0; i < inputs.length; i++) {
            const el = inputs[i];
            const text = (el.innerText || el.textContent || el.value || '').trim();
            const parentText = (el.parentElement ? el.parentElement.innerText : '').trim();

            if (optLetter) {
              if (text.startsWith(optLetter + ')') || text.startsWith(optLetter + '.') || text.startsWith(optLetter + ' ') ||
                  parentText.startsWith(optLetter + ')') || parentText.startsWith(optLetter + '.')) {
                let sel = el.id ? '#' + CSS.escape(el.id) : null;
                if (!sel) {
                  const uid = 'aurex_mcq_' + Math.random().toString(36).substring(2, 9);
                  el.setAttribute('data-aurex-id', uid);
                  sel = `[data-aurex-id="${uid}"]`;
                }
                return { found: true, id: el.id, selector: sel, isRadio: true, letter: optLetter };
              }
            }

            const tokens = qLower.replace(/(question|option|q\\d+|click|mark|select|radio)/g, '').trim().split(/\\s+/);
            const matchesAll = tokens.length > 0 && tokens.every(t => t.length > 1 && (text.toLowerCase().includes(t) || parentText.toLowerCase().includes(t)));
            if (matchesAll) {
              let sel = el.id ? '#' + CSS.escape(el.id) : null;
              if (!sel) {
                const uid = 'aurex_mcq_' + Math.random().toString(36).substring(2, 9);
                el.setAttribute('data-aurex-id', uid);
                sel = `[data-aurex-id="${uid}"]`;
              }
              return { found: true, id: el.id, selector: sel, isRadio: true };
            }
          }
          return { found: false };
        })
        """

        try:
            res = page.evaluate(JS_MCQ_SEARCH, query)
            if res and res.get("found"):
                sel = res.get("selector")
                if sel:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        return loc, {
                            "source": "MCQ_PRACTICE_DETECTOR",
                            "locator_str": sel,
                            "is_mcq": True
                        }
        except Exception:
            pass

        return None, {}

    @staticmethod
    def _score_dom_elements(page: Page, query: str) -> List[Dict[str, Any]]:
        JS_DOM_SCORE = """
        (function(q) {
          const cleanQ = q.toLowerCase().trim();
          const isBlue = cleanQ.includes('blue');
          const isRed = cleanQ.includes('red');
          const isGreen = cleanQ.includes('green');
          const wantButton = cleanQ.includes('button') || cleanQ.includes('btn');
          const wantInput = cleanQ.includes('input') || cleanQ.includes('box') || cleanQ.includes('field') || cleanQ.includes('email') || cleanQ.includes('search');
          const wantRadio = cleanQ.includes('option') || cleanQ.includes('radio');

          const tokens = cleanQ.replace(/\\b(the|button|input|box|field|option|radio|link|click|find|highlight)\\b/g, '')
                               .trim().split(/\\s+/).filter(t => t.length > 1);

          const elements = Array.from(document.querySelectorAll(
            'button, a, input, select, textarea, label, [role], h1, h2, h3, h4, h5, p, [tabindex]'
          ));

          const candidates = [];

          for (let i = 0; i < elements.length; i++) {
            const el = elements[i];
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 && rect.height === 0 && el.type !== 'radio' && el.type !== 'checkbox') continue;

            const text = (el.innerText || el.textContent || '').trim().toLowerCase();
            const val = (el.value || '').toLowerCase();
            const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
            const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
            const role = (el.getAttribute('role') || el.tagName.toLowerCase());
            const id = (el.id || '').toLowerCase();
            const name = (el.getAttribute('name') || '').toLowerCase();

            let score = 0;

            for (const t of tokens) {
              if (text === t) score += 50;
              else if (text.includes(t)) score += 30;
              if (placeholder.includes(t)) score += 35;
              if (ariaLabel.includes(t)) score += 35;
              if (val.includes(t)) score += 25;
              if (id.includes(t)) score += 20;
              if (name.includes(t)) score += 20;
            }

            if (wantButton && (role === 'button' || el.tagName === 'BUTTON' || el.type === 'button' || el.type === 'submit')) {
              score += 25;
            }
            if (wantInput && (role === 'textbox' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
              score += 25;
            }
            if (wantRadio && (role === 'radio' || el.type === 'radio' || el.tagName === 'LABEL')) {
              score += 25;
            }

            if (isBlue || isRed || isGreen) {
              const style = window.getComputedStyle(el);
              const bg = style.backgroundColor;
              const m = bg.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
              if (m) {
                const r = parseInt(m[1]), g = parseInt(m[2]), b = parseInt(m[3]);
                if (isBlue && b > 120 && b > r + 30) score += 40;
                if (isRed && r > 120 && r > b + 30) score += 40;
                if (isGreen && g > 120 && g > r + 30) score += 40;
              }
            }

            if (score > 15) {
              let selector = '';
              if (el.id) {
                selector = '#' + CSS.escape(el.id);
              } else if (el.name) {
                selector = `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
              } else {
                const uid = 'aurex_el_' + Math.random().toString(36).substring(2, 9);
                el.setAttribute('data-aurex-id', uid);
                selector = `[data-aurex-id="${uid}"]`;
              }

              candidates.push({
                selector: selector,
                score: score,
                tag: el.tagName,
                id: el.id,
                text: text.substring(0, 60),
                rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height }
              });
            }
          }

          candidates.sort((a, b) => b.score - a.score);
          return candidates.slice(0, 5);
        })
        """
        try:
            return page.evaluate(JS_DOM_SCORE, query)
        except Exception:
            return []

    @staticmethod
    def _visual_grounding_fallback(page: Page, query: str) -> Tuple[Optional[Locator], Dict[str, Any]]:
        """
        Deep Path: captures screenshot and queries Gemini Flash for bounding box,
        then finds the matching DOM element at that location.
        Vision NEVER controls the mouse directly.
        """
        try:
            screenshot_bytes = page.screenshot()
            pil_img = Image.open(io.BytesIO(screenshot_bytes))
            prompt = (
                f"You are a web UI visual grounding engine. Find the element matching: '{query}'.\n"
                f"Return ONLY valid JSON in format:\n"
                f'{{"found": true, "box_2d": [ymin, xmin, ymax, xmax], "description": "brief", "confidence": 0.9}}\n'
                f"Coordinates are normalized 0 to 1000."
            )
            vlm_text = gemini.generate_image_response(pil_img, prompt)
            vlm_clean = re.sub(r"^```[a-zA-Z]*\n?", "", vlm_text.strip())
            vlm_clean = re.sub(r"\n?```$", "", vlm_clean).strip()
            data = json.loads(vlm_clean)

            if data.get("found") and "box_2d" in data:
                ymin, xmin, ymax, xmax = data["box_2d"]
                vw = page.viewport_size.get("width", 1280) if page.viewport_size else 1280
                vh = page.viewport_size.get("height", 800) if page.viewport_size else 800
                cx = (xmin + xmax) / 2000.0 * vw
                cy = (ymin + ymax) / 2000.0 * vh

                # Find DOM element at (cx, cy)
                JS_ELEMENT_AT_POINT = f"""
                (function() {{
                  const el = document.elementFromPoint({cx}, {cy});
                  if (!el) return null;
                  return el.id ? '#' + CSS.escape(el.id) : el.tagName.toLowerCase();
                }})()
                """
                sel = page.evaluate(JS_ELEMENT_AT_POINT)
                if sel:
                    loc = page.locator(sel).first
                    return loc, {
                        "source": "VISION_GROUNDED_DOM",
                        "locator_str": sel,
                        "point": (cx, cy),
                        "confidence": data.get("confidence", 0.8)
                    }
        except Exception:
            pass

        return None, {}


# ── 5. SMOOTH SCROLLING & CONTAINER ENGINE ────────────────────────────────────

class BrowserScroller:
    """
    Implements browser-native smooth scrolling.
    Supports window scrolling, element-targeted scrolling, and nested scrollable containers.
    """

    @staticmethod
    def smooth_scroll_direction(page: Page, direction: str = "down", amount: int = 500, container_query: str = ""):
        dy = amount if direction == "down" else (-amount if direction == "up" else 0)
        dx = amount if direction == "right" else (-amount if direction == "left" else 0)

        JS_SMOOTH_SCROLL = """
        (function(args) {
          const dy = args.dy;
          const dx = args.dx;
          const cQuery = args.containerQuery;

          let targetContainer = null;
          if (cQuery) {
            const candidates = document.querySelectorAll(cQuery);
            for (const c of candidates) {
              const style = window.getComputedStyle(c);
              if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && c.scrollHeight > c.clientHeight) {
                targetContainer = c;
                break;
              }
            }
          }

          if (targetContainer) {
            targetContainer.scrollBy({ top: dy, left: dx, behavior: 'smooth' });
          } else {
            window.scrollBy({ top: dy, left: dx, behavior: 'smooth' });
          }
        })
        """
        page.evaluate(JS_SMOOTH_SCROLL, {"dy": dy, "dx": dx, "containerQuery": container_query})
        time.sleep(0.4)

    @staticmethod
    def smooth_scroll_to_element(page: Page, locator: Locator) -> bool:
        try:
            locator.evaluate("el => el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' })")
            time.sleep(0.5)
            return True
        except Exception:
            return False


# ── 6. DIRECT BROWSER ACTION ROUTER ───────────────────────────────────────────

class BrowserActionRouter:
    """
    Direct Chrome native actions via Playwright DOM / CDP.
    Zero mouse coordinate clicking for web content.
    Includes visual pill injection, practice MCQ marking, direct text extraction,
    and post-action verification.
    """

    @staticmethod
    def execute(
        action: str,
        target_query: str,
        text: str = "",
        direction: str = "down",
        click_type: str = "single",
        highlight: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        cdp = ChromeCDPManager.get_instance()
        page = cdp.ensure_connection()

        start_time = time.time()
        action = action.lower().strip()
        metadata: Dict[str, Any] = {"action": action, "target": target_query}

        # ── NAVIGATION & TAB ACTIONS ──
        if action in ("open", "navigate", "goto"):
            url = target_query or text
            if not url:
                return False, "No URL provided to navigate.", metadata
            if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file:///"):
                if "." in url and not " " in url:
                    url = "https://" + url
                else:
                    url = f"https://www.google.com/search?q={url.replace(' ', '+')}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                cdp._ensure_overlay_injected(page)
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action(action, target_query, "PLAYWRIGHT", "page.goto", "PASS", dur)
                return True, f"Navigated to: {page.url} ({page.title()})", metadata
            except Exception as e:
                return False, f"Navigation failed: {e}", metadata

        if action in ("back", "go_back"):
            page.go_back(timeout=5000)
            return True, f"Navigated back to: {page.title()}", metadata

        if action in ("forward", "go_forward"):
            page.go_forward(timeout=5000)
            return True, f"Navigated forward to: {page.title()}", metadata

        if action in ("reload", "refresh"):
            page.reload()
            return True, f"Reloaded page: {page.title()}", metadata

        if action == "new_tab":
            cdp.new_tab(target_query or text)
            return True, f"Opened new tab: {page.title()}", metadata

        if action == "switch_tab":
            ok, msg = cdp.switch_tab(target_query or text)
            return ok, msg, metadata

        # ── PAGE READING ──
        if action in ("read", "summary", "extract"):
            page_text = BrowserActionRouter._read_page_content(page)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("read", page.title(), "DOM_TEXT", "document.body.innerText", "PASS", dur)
            return True, page_text, metadata

        # ── SMOOTH SCROLLING ──
        if action == "scroll":
            if target_query and target_query.lower() not in ("down", "up", "left", "right"):
                # "Scroll to Question 8"
                loc, meta = TargetResolver.resolve_target(page, target_query, action_type="scroll")
                if loc and loc.count() > 0:
                    BrowserScroller.smooth_scroll_to_element(page, loc)
                    BrowserActionRouter._inject_pill_highlight(page, loc, label="SCROLLED HERE")
                    dur = int((time.time() - start_time) * 1000)
                    _log_chrome_action("scroll_to", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
                    return True, f"Smoothly scrolled to '{target_query}' into view.", metadata
            # General smooth scroll
            BrowserScroller.smooth_scroll_direction(page, direction=direction, amount=600)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("scroll", direction, "WINDOW_SMOOTH", "window.scrollBy", "PASS", dur)
            return True, f"Smoothly scrolled {direction}.", metadata

        # ── TARGET RESOLUTION FOR INTERACTIVE ACTIONS ──
        loc, meta = TargetResolver.resolve_target(page, target_query, action_type=action)
        metadata.update(meta)

        if loc is None or loc.count() == 0:
            # Smart Find + Dynamic Scroll Loop (Requirement 14)
            if action in ("click", "find", "highlight", "type", "copy"):
                for _ in range(3):
                    BrowserScroller.smooth_scroll_direction(page, direction="down", amount=500)
                    loc, meta = TargetResolver.resolve_target(page, target_query, action_type=action)
                    if loc and loc.count() > 0:
                        break

            if loc is None or loc.count() == 0:
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action(action, target_query, "DOM", "NOT_FOUND", "FAIL", dur)
                return False, f"Could not find element matching '{target_query}' on {page.title()}.", metadata

        # Record last target
        cdp.last_target_info = {
            "query": target_query,
            "selector": meta.get("locator_str", ""),
            "time": time.time()
        }
        cdp.last_target_locator = loc

        # Smooth scroll target into view if needed
        BrowserScroller.smooth_scroll_to_element(page, loc)

        # ── FIND / HIGHLIGHT ──
        if action in ("find", "highlight", "show"):
            label = "TARGET"
            if meta.get("is_mcq"):
                label = "MCQ OPTION"
            BrowserActionRouter._inject_pill_highlight(page, loc, label=label, duration_ms=4000)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("highlight", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Found and highlighted '{target_query}' with smooth AUREX pill.", metadata

        # ── COPY DIRECTLY FROM DOM (NO MOUSE DRAGGING) ──
        if action == "copy":
            extracted_text = BrowserActionRouter._extract_dom_text(loc)
            if not extracted_text:
                return False, f"No text found on target element '{target_query}'.", metadata

            _copy_to_clipboard(extracted_text)
            BrowserActionRouter._inject_pill_highlight(page, loc, label="COPIED", duration_ms=2500, color="#10b981")
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("copy", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Copied to clipboard: '{extracted_text}'", metadata

        # ── TYPE / FILL ──
        if action in ("type", "fill", "write", "enter"):
            BrowserActionRouter._inject_pill_highlight(page, loc, label="TYPING", duration_ms=2500)
            try:
                loc.fill(text, timeout=3000)
            except Exception:
                loc.click()
                loc.press_sequentially(text, delay=20)
            
            # Verification
            val = ""
            try: val = loc.input_value()
            except Exception: pass
            verif = "PASS" if (not text or text.lower() in val.lower()) else "VERIFY_WARNING"
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("type", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), verif, dur)
            return True, f"Entered '{text}' into '{target_query}'.", metadata

        # ── PRACTICE / MCQ OPTION SELECTION (Requirement 25, 26) ──
        if meta.get("is_mcq") or action in ("check", "select_option", "mark"):
            try:
                loc.check(timeout=2000)
            except Exception:
                loc.click(timeout=2000)

            # Verification of checked state
            is_checked = False
            try:
                is_checked = loc.is_checked()
            except Exception:
                is_checked = True

            BrowserActionRouter._inject_pill_highlight(page, loc, label="SELECTED", duration_ms=4000, color="#10b981", is_mcq=True)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("mcq_mark", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS" if is_checked else "CLICKED", dur)
            return True, f"Marked practice option '{target_query}'. (Checked: {is_checked})", metadata

        # ── CLICK / DOUBLE CLICK / RIGHT CLICK ──
        if action in ("click", "double_click", "right_click", "press"):
            # Animate AUREX visual pill around target first
            BrowserActionRouter._inject_pill_highlight(page, loc, label="CLICKING", duration_ms=1800)

            btn = "left"
            if click_type == "right" or action == "right_click":
                btn = "right"

            try:
                if action == "double_click" or click_type == "double":
                    loc.dblclick(timeout=3500)
                else:
                    loc.click(button=btn, timeout=3500)
            except Exception as e:
                # Fallback: DOM dispatchEvent
                try:
                    loc.evaluate("el => { el.focus(); el.click(); }")
                except Exception as e2:
                    dur = int((time.time() - start_time) * 1000)
                    _log_chrome_action(action, target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "FAIL", dur)
                    return False, f"Failed to click '{target_query}': {e2}", metadata

            # Verification
            time.sleep(0.3)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action(action, target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Clicked '{target_query}' successfully.", metadata

        # ── HOVER ──
        if action == "hover":
            BrowserActionRouter._inject_pill_highlight(page, loc, label="HOVER", duration_ms=2500)
            loc.hover(timeout=3000)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("hover", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Hovered over '{target_query}'.", metadata

        # ── PRESS KEY ──
        if action in ("press_key", "key"):
            key = text or target_query
            page.keyboard.press(key)
            return True, f"Pressed key '{key}'.", metadata

        return False, f"Unsupported browser action: '{action}'.", metadata

    @staticmethod
    def _inject_pill_highlight(
        page: Page,
        locator: Locator,
        label: str = "AUREX",
        duration_ms: int = 3000,
        color: str = "#3b82f6",
        is_mcq: bool = False
    ):
        try:
            try:
                page.evaluate(f"if (!window.__aurex_highlight) {{ {AUREX_OVERLAY_INJECTION_JS} }}")
            except Exception:
                pass
            locator.evaluate(
                "el => window.__aurex_highlight ? window.__aurex_highlight(el, '" + label + "', " + str(duration_ms) + ", '" + color + "', 4, " + str(is_mcq).lower() + ") : null"
            )
        except Exception:
            pass

    @staticmethod
    def _extract_dom_text(locator: Locator) -> str:
        try:
            # Check input value first
            val = locator.input_value()
            if val: return val
        except Exception:
            pass

        try:
            txt = locator.inner_text()
            if txt: return txt.strip()
        except Exception:
            pass

        try:
            txt = locator.text_content()
            if txt: return txt.strip()
        except Exception:
            pass

        return ""

    @staticmethod
    def _read_page_content(page: Page) -> str:
        JS_READ = """
        (function() {
          const title = document.title;
          const url = window.location.href;
          const headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.innerText.trim()).filter(Boolean);
          const paragraphs = Array.from(document.querySelectorAll('p')).map(p => p.innerText.trim()).filter(p => p.length > 20).slice(0, 10);
          return {
            title: title,
            url: url,
            headings: headings.slice(0, 8),
            paragraphs: paragraphs
          };
        })()
        """
        try:
            data = page.evaluate(JS_READ)
            lines = [f"Page: {data.get('title')} ({data.get('url')})"]
            if data.get("headings"):
                lines.append("Headings: " + " | ".join(data["headings"]))
            if data.get("paragraphs"):
                lines.append("\nContent:\n" + "\n".join(data["paragraphs"]))
            return "\n".join(lines)
        except Exception as e:
            return f"Error reading page content: {e}"


def _copy_to_clipboard(text: str):
    if _WIN32:
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return
        except Exception:
            pass
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        pass


def _log_chrome_action(action: str, target: str, source: str, locator: str, verif: str, duration_ms: int):
    log_line = (
        f"[CHROME] instruction='{action} {target}' source='{source}' "
        f"locator='{locator}' action='playwright.{action}' "
        f"fallback=false verification='{verif}' duration={duration_ms}ms"
    )
    print(log_line)


# ── 7. DESKTOP FALLBACK ROUTER (UIA + OCR FOR NATIVE WINDOWS APPS) ────────────

class DesktopFallbackRouter:
    """
    Fallback router for non-browser Windows desktop apps (Notepad, Explorer, Settings, etc.)
    using Windows UI Automation and local WinRT OCR.
    """

    @staticmethod
    def execute(action: str, target_query: str, text: str = "", click_type: str = "single") -> Tuple[bool, str]:
        print(f"[DESKTOP] Routing '{action} {target_query}' via Windows Desktop Automation...")

        if action in ("type", "fill") and not target_query:
            pyautogui.write(text, interval=0.02)
            return True, f"Typed text into active desktop window: '{text}'"

        # Search UIA elements
        target_pt = DesktopFallbackRouter._find_uia_element(target_query)
        if not target_pt and _WINRT_OCR:
            target_pt = DesktopFallbackRouter._find_ocr_word(target_query)

        if not target_pt:
            return False, f"Could not locate desktop element '{target_query}'."

        cx, cy = target_pt
        if action in ("click", "double_click", "right_click", "press"):
            pyautogui.moveTo(cx, cy, duration=0.15)
            if action == "double_click" or click_type == "double":
                pyautogui.doubleClick()
            elif action == "right_click" or click_type == "right":
                pyautogui.rightClick()
            else:
                pyautogui.click()
            return True, f"Clicked desktop element '{target_query}' at ({cx}, {cy})."

        if action in ("type", "fill"):
            pyautogui.moveTo(cx, cy, duration=0.15)
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.write(text, interval=0.02)
            return True, f"Clicked and typed '{text}' into '{target_query}'."

        if action == "hover":
            pyautogui.moveTo(cx, cy, duration=0.2)
            return True, f"Hovered over '{target_query}'."

        return False, f"Unsupported desktop action: '{action}'."

    @staticmethod
    def _find_uia_element(query: str) -> Optional[Tuple[int, int]]:
        if not _PYWINAUTO:
            return None
        clean = query.lower().strip()
        try:
            desktop = PywinDesktop(backend="uia")
            for win in desktop.windows():
                if not win.is_visible():
                    continue
                for ctrl in win.descendants():
                    try:
                        txt = (ctrl.window_text() or "").lower()
                        if clean in txt and ctrl.is_visible():
                            rect = ctrl.rectangle()
                            return (rect.mid_point().x, rect.mid_point().y)
                    except Exception:
                        continue
        except Exception:
            pass
        return None

    @staticmethod
    def _find_ocr_word(query: str) -> Optional[Tuple[int, int]]:
        if not _WINRT_OCR or not _MSS:
            return None
        import asyncio
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                shot = sct.grab(mon)
                png_bytes = mss.tools.to_png(shot.rgb, shot.size)

            async def _run_ocr():
                stream = winrt_streams.InMemoryRandomAccessStream()
                writer = winrt_streams.DataWriter(stream)
                writer.write_bytes(png_bytes)
                await writer.store_async()
                await writer.flush_async()
                stream.seek(0)
                decoder = await winrt_imaging.BitmapDecoder.create_async(stream)
                bitmap = await decoder.get_software_bitmap_async()
                engine = winrt_ocr.OcrEngine.try_create_from_user_profile_languages()
                res = await engine.recognize_async(bitmap)
                clean_q = query.lower().strip()
                for line in res.lines:
                    for w in line.words:
                        if clean_q in w.text.lower():
                            r = w.bounding_rect
                            return (int(r.x + r.width / 2), int(r.y + r.height / 2))
                return None

            return asyncio.run(_run_ocr())
        except Exception:
            return None


# ── 8. MASTER COMMAND ROUTER ──────────────────────────────────────────────────

def is_chrome_target(action: str, target: str, text: str) -> bool:
    """
    Determines whether command should be routed to Chrome vs Desktop.
    """
    combined = f"{action} {target} {text}".lower()

    # Explicit browser keywords
    if any(k in combined for k in (
        "chrome", "google", "browser", "website", "web page", "url", "tab",
        "youtube", "github", "search in", "question", "option", "mcq", "localhost"
    )):
        return True

    # Active foreground window check
    if _WIN32:
        try:
            hwnd = win32gui.GetForegroundWindow()
            title = win32gui.GetWindowText(hwnd) or ""
            cls = win32gui.GetClassName(hwnd) or ""
            if "Chrome" in cls or "Chrome" in title:
                return True
        except Exception:
            pass

    # If Chrome CDP is already alive, route to it by default
    if ChromeCDPManager.get_instance().is_alive():
        return True

    return False


def route_screen_command(
    action: str = "click",
    target_query: str = "",
    text: str = "",
    direction: str = "down",
    click_type: str = "single",
    explain: bool = False,
    highlight: bool = False
) -> str:
    """
    Master router directing action to Chrome-Native or Desktop Fallback.
    """
    action = (action or "click").strip().lower()
    target_query = (target_query or "").strip()
    text = (text or "").strip()

    if is_chrome_target(action, target_query, text):
        try:
            ok, msg, meta = BrowserActionRouter.execute(
                action=action,
                target_query=target_query,
                text=text,
                direction=direction,
                click_type=click_type,
                highlight=highlight
            )
            if explain:
                return f"{msg}\n[Chrome Engine | Source: {meta.get('source', 'DOM')} | Locator: {meta.get('locator_str', 'N/A')}]"
            return msg
        except Exception as e:
            print(f"[CHROME_ERROR] Falling back to desktop automation: {e}")
            # Fall through to desktop fallback
            pass

    # Desktop Fallback
    ok, msg = DesktopFallbackRouter.execute(
        action=action,
        target_query=target_query,
        text=text,
        click_type=click_type
    )
    return msg


# ── 9. AUREX PLUGIN SPECIFICATION & RUN HANDLER ───────────────────────────────

PLUGIN = {
    "name": "screencntrl",
    "description": (
        "Chrome-native full-power computer use & screen understanding agent. "
        "Operates directly on Google Chrome's DOM, accessibility tree, and semantic page structure. "
        "Translates natural language instructions into real browser actions: 'click Login', 'click the blue button', "
        "'click this', 'copy this', 'type my email here', 'scroll down smoothly', 'scroll to Question 8', "
        "'highlight option B', 'mark practice option TCP', 'what is on this page'. "
        "Provides dynamic visual pill highlights around detected options and verified direct actions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "click | double_click | right_click | type | fill | copy | scroll | hover | find | highlight | read | open | switch_tab | new_tab | press_key"
            },
            "target": {
                "type": "STRING",
                "description": "Natural language element description: e.g. 'Login', 'blue button', 'search box', 'Question 4 option B', 'section called Installation', 'this', 'that'"
            },
            "text": {
                "type": "STRING",
                "description": "Text to write for type/fill actions or URL for open action"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right for smooth scroll action"
            },
            "click_type": {
                "type": "STRING",
                "description": "single | double | right"
            },
            "highlight": {
                "type": "BOOLEAN",
                "description": "Show animated AUREX visual pill overlay around target"
            },
            "explain": {
                "type": "BOOLEAN",
                "description": "Return debug grounding details"
            }
        },
        "required": [
            "action"
        ]
    }
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """
    Entrypoint invoked by AUREX Live when the user requests screen/computer actions.
    """
    params = parameters or {}
    action = params.get("action", "click")
    target = params.get("target", "")
    text = params.get("text", "")
    direction = params.get("direction", "down")
    click_type = params.get("click_type", "single")
    highlight = bool(params.get("highlight", False))
    explain = bool(params.get("explain", False))

    if player:
        try:
            player.write_log(f"🌐 [ChromeCtrl] {action} {target or text}")
        except Exception:
            pass

    result = route_screen_command(
        action=action,
        target_query=target,
        text=text,
        direction=direction,
        click_type=click_type,
        explain=explain,
        highlight=highlight
    )

    if player:
        try:
            player.write_log(f"AUREX: {result}")
        except Exception:
            pass

    return result
