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
      0% { box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.10), 0 0 18px rgba(16, 185, 129, 0.35); }
      50% { box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.20), 0 0 24px rgba(16, 185, 129, 0.50); }
      100% { box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.10), 0 0 18px rgba(16, 185, 129, 0.35); }
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
      transition: top 0.08s ease-out, left 0.08s ease-out, width 0.08s ease-out, height 0.08s ease-out, opacity 0.25s ease, transform 0.25s ease !important;
      animation: aurexFadeInScale 0.2s cubic-bezier(0.16, 1, 0.3, 1), aurexPulse 2s infinite ease-in-out !important;
      display: block !important;
      visibility: visible !important;
    }
    .aurex-pill-overlay.mcq-selected, .aurex-mcq-pill {
      border: 3px solid #10b981 !important;
      background: rgba(16, 185, 129, 0.08) !important;
      border-radius: 9999px !important;
      box-sizing: border-box !important;
      pointer-events: none !important;
      position: fixed !important;
      z-index: 2147483647 !important;
      box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.10), 0 0 18px rgba(16, 185, 129, 0.35) !important;
      transition: top 0.08s ease-out, left 0.08s ease-out, width 0.08s ease-out, height 0.08s ease-out, opacity 0.3s ease, transform 0.3s ease !important;
      animation: aurexFadeInScale 0.25s cubic-bezier(0.16, 1, 0.3, 1), aurexMcqPulse 2.5s infinite ease-in-out !important;
      display: block !important;
      visibility: visible !important;
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
      const padX = item.padX !== undefined ? item.padX : (item.isMcq ? 10 : (item.padding || 4));
      const padY = item.padY !== undefined ? item.padY : (item.isMcq ? 6 : (item.padding || 4));
      item.overlay.style.top = (rect.top - padY) + 'px';
      item.overlay.style.left = (rect.left - padX) + 'px';
      item.overlay.style.width = (rect.width + padX * 2) + 'px';
      item.overlay.style.height = (rect.height + padY * 2) + 'px';
      item.overlay.style.display = (rect.width > 0 && rect.height > 0) ? 'block' : 'none';
      item.overlay.style.visibility = (rect.width > 0 && rect.height > 0) ? 'visible' : 'hidden';
    }
  }

  window.addEventListener('scroll', updateAllPositions, { passive: true, capture: true });
  window.addEventListener('resize', updateAllPositions, { passive: true });
  
  const observer = new MutationObserver(() => updateAllPositions());
  const rootTarget = document.documentElement || document.body;
  if (rootTarget) {
    observer.observe(rootTarget, { attributes: true, childList: true, subtree: true });
  }

  window.__aurex_highlight = function(target, label, durationMs, color, padding, isMcq) {
    ensureStyles();
    isMcq = !!isMcq;
    label = label !== undefined ? label : (isMcq ? '' : 'AUREX');
    durationMs = durationMs !== undefined ? durationMs : (isMcq ? 5000 : 3000);
    color = color || (isMcq ? '#10b981' : '#3b82f6');
    padding = padding || 4;

    let el = null;
    if (typeof target === 'string') {
      try { el = document.querySelector(target); } catch(e){}
    } else if (target && target.nodeType === 1) {
      el = target;
    }
    if (!el) return { success: false, reason: "TARGET_NOT_FOUND" };

    if (isMcq) {
      let rect = el.getBoundingClientRect();
      if (rect.width <= 5 || rect.height <= 5) {
        let p = el.parentElement;
        while (p && p !== document.body && p !== document.documentElement) {
          const pr = p.getBoundingClientRect();
          if (pr.width > 20 && pr.height > 15) {
            el = p;
            break;
          }
          p = p.parentElement;
        }
      }
    }

    const initialRect = el.getBoundingClientRect();
    if (isMcq && (initialRect.width <= 5 || initialRect.height <= 5)) {
      return { success: false, reason: "TARGET_TOO_SMALL_OR_HIDDEN" };
    }

    const padX = isMcq ? 10 : padding;
    const padY = isMcq ? 6 : padding;

    const overlay = document.createElement('div');
    overlay.className = 'aurex-pill-overlay' + (isMcq ? ' mcq-selected' : '');
    
    if (isMcq) {
      overlay.style.border = '3px solid #10b981';
      overlay.style.background = 'rgba(16, 185, 129, 0.08)';
      overlay.style.borderRadius = '9999px';
      overlay.style.boxSizing = 'border-box';
      overlay.style.pointerEvents = 'none';
      overlay.style.position = 'fixed';
      overlay.style.zIndex = '2147483647';
      overlay.style.boxShadow = '0 0 0 2px rgba(16, 185, 129, 0.10), 0 0 18px rgba(16, 185, 129, 0.35)';
      overlay.style.display = 'block';
      overlay.style.visibility = 'visible';
      overlay.style.opacity = '1';
    } else {
      overlay.style.borderColor = color;
      overlay.style.background = color.startsWith('#') ? (color + '18') : 'rgba(59, 130, 246, 0.09)';
      overlay.style.borderRadius = '10px';
    }

    if (label && !isMcq) {
      const badge = document.createElement('div');
      badge.className = 'aurex-pill-badge';
      badge.style.background = color;
      badge.textContent = label;
      overlay.appendChild(badge);
    }

    overlay.style.top = (initialRect.top - padY) + 'px';
    overlay.style.left = (initialRect.left - padX) + 'px';
    overlay.style.width = (initialRect.width + padX * 2) + 'px';
    overlay.style.height = (initialRect.height + padY * 2) + 'px';

    const rootContainer = document.documentElement || document.body;
    rootContainer.appendChild(overlay);

    const oRect = overlay.getBoundingClientRect();
    if (oRect.width <= 10 || oRect.height <= 10) {
      if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
      return { success: false, reason: "OVERLAY_TOO_SMALL", width: oRect.width, height: oRect.height };
    }

    const record = {
      element: el,
      overlay: overlay,
      padding: padding,
      padX: padX,
      padY: padY,
      isMcq: isMcq
    };
    window.__aurex_active_overlays.push(record);
    updateAllPositions();

    if (durationMs > 0) {
      setTimeout(() => {
        overlay.style.opacity = '0';
        overlay.style.transform = isMcq ? 'scale(0.97)' : 'scale(0.92)';
        setTimeout(() => {
          if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
          const idx = window.__aurex_active_overlays.indexOf(record);
          if (idx !== -1) window.__aurex_active_overlays.splice(idx, 1);
        }, 300);
      }, durationMs);
    }

    return {
      success: true,
      pillCreated: true,
      targetTag: el.tagName,
      rect: {
        x: Math.round(oRect.left),
        y: Math.round(oRect.top),
        w: Math.round(oRect.width),
        h: Math.round(oRect.height)
      }
    };
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
    def _extract_ordinal_and_query(q: str) -> Tuple[Optional[int], str]:
        """
        Extracts ordinal indicator (first/1st, second/2nd, etc.) from query.
        Returns (ordinal_index, cleaned_query).
        """
        ord_map = {
            "first": 0, "1st": 0,
            "second": 1, "2nd": 1,
            "third": 2, "3rd": 2,
            "fourth": 3, "4th": 3,
            "fifth": 4, "5th": 4,
            "sixth": 5, "6th": 5,
            "last": -1, "final": -1,
        }
        pattern = r"\b(the\s+)?(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|sixth|6th|last|final)\b"
        m = re.search(pattern, q, flags=re.I)
        if m:
            ord_key = m.group(2).lower()
            clean = re.sub(pattern, "", q, count=1, flags=re.I).strip()
            clean = re.sub(r"\s+", " ", clean).strip()
            return ord_map.get(ord_key), clean
        return None, q

    @staticmethod
    def resolve_target(page: Page, query: str, action_type: str = "click") -> Tuple[Optional[Locator], Dict[str, Any]]:
        raw_clean = TargetResolver._clean_query(query)
        ord_idx, clean_q = TargetResolver._extract_ordinal_and_query(raw_clean)
        
        metadata: Dict[str, Any] = {
            "source": "UNKNOWN",
            "locator_str": "",
            "text": "",
            "score": 0.0,
            "ordinal": ord_idx
        }

        def _pick(cand_loc: Optional[Locator], idx: Optional[int]) -> Optional[Locator]:
            if cand_loc is None:
                return None
            try:
                cnt = cand_loc.count()
                if cnt == 0:
                    return None
                if idx is None:
                    return cand_loc.first
                if idx == -1:
                    return cand_loc.last
                if 0 <= idx < cnt:
                    return cand_loc.nth(idx)
                return cand_loc.first
            except Exception:
                return cand_loc.first

        # 1. Handle Contextual "this" / "that"
        is_contextual = not clean_q or clean_q in (
            "this", "that", "it", "here", "selected",
            "this mcq", "this option", "this answer",
            "the option", "the answer", "mcq", "option"
        )
        if is_contextual:
            cdp = ChromeCDPManager.get_instance()
            cand_loc = None
            if cdp.last_target_locator is not None:
                try:
                    if cdp.last_target_locator.count() > 0:
                        cand_loc = cdp.last_target_locator
                        metadata.update({"source": "CONTEXT_HISTORY_LOCATOR", "locator_str": "last_target_locator"})
                except Exception:
                    pass

            if cand_loc is None:
                last_target = cdp.last_target_info
                if last_target and last_target.get("selector") and not last_target.get("selector", "").startswith("get_by_"):
                    try:
                        loc = page.locator(last_target["selector"]).first
                        if loc.count() > 0:
                            cand_loc = loc
                            metadata.update({"source": "CONTEXT_HISTORY", "locator_str": last_target["selector"]})
                    except Exception:
                        pass

            if cand_loc is None:
                try:
                    loc = page.locator("*:focus").first
                    if loc.count() > 0:
                        cand_loc = loc
                        metadata.update({"source": "DOM_ACTIVE_FOCUS", "locator_str": "*:focus"})
                except Exception:
                    pass

            if cand_loc is not None:
                vis_loc, vis_meta = TargetResolver._resolve_mcq_visual_target(page, cand_loc)
                if vis_loc is not None and vis_meta.get("is_mcq"):
                    metadata.update(vis_meta)
                    return vis_loc, metadata
                return cand_loc, metadata

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
                    h_loc = page.get_by_role("heading", name=re.compile(rf"{re.escape(sec_name)}", re.I))
                    target_h = _pick(h_loc, ord_idx)
                    if target_h and target_h.count() > 0:
                        metadata.update({"source": "SECTION_HEADING", "locator_str": f"heading('{sec_name}')"})
                        return target_h, metadata
                except Exception:
                    pass

        # 3. Role-Based Semantic Targeting
        role_hint, name_hint = TargetResolver._extract_role_and_name(clean_q)
        if role_hint:
            try:
                role_loc = page.get_by_role(role_hint, name=re.compile(rf"{re.escape(name_hint)}", re.I))
                target_role = _pick(role_loc, ord_idx)
                if target_role and target_role.count() > 0 and target_role.is_visible():
                    metadata.update({
                        "source": "ROLE_ACCESSIBLE_NAME",
                        "locator_str": f"get_by_role('{role_hint}', name='{name_hint}')",
                        "text": name_hint
                    })
                    return target_role, metadata
            except Exception:
                pass

        # 4. Standard User-Facing Semantic Locators
        # Label
        try:
            lbl_loc = page.get_by_label(re.compile(rf"{re.escape(clean_q)}", re.I))
            target_lbl = _pick(lbl_loc, ord_idx)
            if target_lbl and target_lbl.count() > 0 and target_lbl.is_visible():
                metadata.update({"source": "GET_BY_LABEL", "locator_str": f"get_by_label('{clean_q}')"})
                return target_lbl, metadata
        except Exception:
            pass

        # Placeholder (especially for inputs)
        try:
            ph_loc = page.get_by_placeholder(re.compile(rf"{re.escape(clean_q)}", re.I))
            target_ph = _pick(ph_loc, ord_idx)
            if target_ph and target_ph.count() > 0 and target_ph.is_visible():
                metadata.update({"source": "GET_BY_PLACEHOLDER", "locator_str": f"get_by_placeholder('{clean_q}')"})
                return target_ph, metadata
        except Exception:
            pass

        # Button by text
        try:
            btn_loc = page.get_by_role("button", name=re.compile(rf"{re.escape(clean_q)}", re.I))
            target_btn = _pick(btn_loc, ord_idx)
            if target_btn and target_btn.count() > 0 and target_btn.is_visible():
                metadata.update({"source": "BUTTON_BY_TEXT", "locator_str": f"get_by_role('button', name='{clean_q}')"})
                return target_btn, metadata
        except Exception:
            pass

        # Link by text
        try:
            lnk_loc = page.get_by_role("link", name=re.compile(rf"{re.escape(clean_q)}", re.I))
            target_lnk = _pick(lnk_loc, ord_idx)
            if target_lnk and target_lnk.count() > 0 and target_lnk.is_visible():
                metadata.update({"source": "LINK_BY_TEXT", "locator_str": f"get_by_role('link', name='{clean_q}')"})
                return target_lnk, metadata
        except Exception:
            pass

        # Text Locator
        try:
            txt_loc = page.get_by_text(re.compile(rf"{re.escape(clean_q)}", re.I), exact=False)
            target_txt = _pick(txt_loc, ord_idx)
            if target_txt and target_txt.count() > 0 and target_txt.is_visible():
                metadata.update({"source": "GET_BY_TEXT", "locator_str": f"get_by_text('{clean_q}')"})
                return target_txt, metadata
        except Exception:
            pass

        # 4b. Common Icon / Action Controls
        icon_queries = {
            "close": ["button[aria-label*='close' i]", "button.close", "[aria-label*='dismiss' i]", "[title*='close' i]", "button[data-action*='close' i]"],
            "cancel": ["button[aria-label*='cancel' i]", "button:has-text('Cancel')"],
            "menu": ["button[aria-label*='menu' i]", "[aria-label*='navigation' i]", "button[id*='menu' i]", "button.menu-toggle"],
            "settings": ["button[aria-label*='setting' i]", "[aria-label*='preference' i]", "[title*='setting' i]"],
            "search": ["button[aria-label*='search' i]", "input[type='search']", "input[name*='search' i]", "[placeholder*='search' i]"],
            "refresh": ["button[aria-label*='refresh' i]", "button[aria-label*='reload' i]"],
            "copy": ["button[aria-label*='copy' i]", "button[title*='copy' i]", "[data-testid*='copy' i]"],
            "submit": ["button[type='submit']", "input[type='submit']", "button:has-text('Submit')"],
        }
        for key, sel_list in icon_queries.items():
            if key in clean_q.lower():
                for sel in sel_list:
                    try:
                        cand = page.locator(sel)
                        target_el = _pick(cand, ord_idx)
                        if target_el and target_el.count() > 0 and target_el.is_visible():
                            metadata.update({"source": "ICON_CONTROL", "locator_str": sel})
                            return target_el, metadata
                    except Exception:
                        pass

        # 4c. Enhanced Form & Input Attribute Selectors
        if action_type in ("type", "fill", "write", "enter", "click", "clear") or any(k in clean_q.lower() for k in ("input", "field", "box", "email", "password", "user", "name", "prompt", "message", "search", "code")):
            attr_selectors = [
                f"input[name*='{clean_q}' i], textarea[name*='{clean_q}' i]",
                f"input[id*='{clean_q}' i], textarea[id*='{clean_q}' i]",
                f"input[placeholder*='{clean_q}' i], textarea[placeholder*='{clean_q}' i]",
                f"[aria-label*='{clean_q}' i]",
                f"[data-testid*='{clean_q}' i]",
                f"[title*='{clean_q}' i]",
                f"[contenteditable='true'][aria-label*='{clean_q}' i]",
                f"[contenteditable='true'][placeholder*='{clean_q}' i]",
                f"[role='textbox'][aria-label*='{clean_q}' i]",
            ]
            for sel in attr_selectors:
                try:
                    cand = page.locator(sel)
                    target_el = _pick(cand, ord_idx)
                    if target_el and target_el.count() > 0 and target_el.is_visible():
                        metadata.update({"source": "ATTRIBUTE_SELECTOR", "locator_str": sel})
                        return target_el, metadata
                except Exception:
                    pass

            # Generic rich contenteditable if prompt/message is asked and no specific element found
            if clean_q.lower() in ("prompt", "message", "chat", "textbox", "input", "box", "field", "text"):
                for sel in ["[contenteditable='true']", "[role='textbox']", "textarea", "input[type='text']"]:
                    try:
                        cand = page.locator(sel)
                        target_el = _pick(cand, ord_idx)
                        if target_el and target_el.count() > 0 and target_el.is_visible():
                            metadata.update({"source": "GENERIC_EDITABLE", "locator_str": sel})
                            return target_el, metadata
                    except Exception:
                        pass

        # 5. Semantic In-Page DOM Scoring (Inspects colors, hierarchy, and tokens)
        ranked = TargetResolver._score_dom_elements(page, clean_q)
        if ranked:
            top = ranked[0]
            sel = top.get("selector")
            if sel:
                loc = page.locator(sel)
                target_loc = _pick(loc, ord_idx)
                if target_loc and target_loc.count() > 0:
                    metadata.update({
                        "source": "DOM_SEMANTIC_SCORING",
                        "locator_str": sel,
                        "text": top.get("text", ""),
                        "score": top.get("score", 0.0)
                    })
                    return target_loc, metadata

        # 6. Deep Path: Visual Grounding if Canvas or pure graphic
        vis_loc, vis_meta = TargetResolver._visual_grounding_fallback(page, clean_q)
        if vis_loc is not None:
            return vis_loc, vis_meta

        return None, metadata

    @staticmethod
    def _clean_query(q: str) -> str:
        s = q.strip()
        # Strip polite fillers first
        s = re.sub(r"^(?:please|can you|could you|would you|kindly|now|just)\s+", "", s, flags=re.I)
        # Remove common command prefixes (longer phrases first to avoid partial matches)
        s = re.sub(
            r"^(?:"
            r"navigate to|go to|scroll to|scroll down to|scroll up to|focus on|switch to|"
            r"type into|type in|fill in|write in|write to|"
            r"click on|click the|click|"
            r"double.click|right.click|"
            r"press on|press|"
            r"tap on|tap|"
            r"select option|select|"
            r"open up|open|"
            r"find the|find|"
            r"highlight the|highlight|"
            r"copy the|copy|"
            r"type|fill|write|"
            r"clear out|clear|erase|"
            r"mark the|mark|"
            r"circle the|circle|"
            r"check the|check|"
            r"choose the|choose|"
            r"show the|show|"
            r"hover over|hover|"
            r"search for|search"
            r")\s+",
            "", s, flags=re.I
        )
        # Remove leading articles
        s = re.sub(r"^(?:the|a|an)\s+", "", s, flags=re.I)
        # Remove trailing punctuation
        s = re.sub(r"[.?!,]+$", "", s).strip()
        return s

    @staticmethod
    def _extract_role_and_name(q: str) -> Tuple[Optional[str], str]:
        ql = q.lower().strip()
        if "button" in ql or "btn" in ql:
            name = re.sub(r"\b(?:button|btn)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the|blue|green|red|primary|secondary)\s+", "", name, flags=re.I).strip()
            return "button", name or q
        if "link" in ql:
            name = re.sub(r"\b(?:link|hyperlink)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the)\s+", "", name, flags=re.I).strip()
            return "link", name or q
        if "checkbox" in ql:
            name = re.sub(r"\b(?:checkbox|check box)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the)\s+", "", name, flags=re.I).strip()
            return "checkbox", name or q
        if "radio" in ql:
            name = re.sub(r"\b(?:radio|radio button)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the)\s+", "", name, flags=re.I).strip()
            return "radio", name or q
        if "search" in ql and ("box" in ql or "field" in ql or "input" in ql or "bar" in ql):
            name = re.sub(r"\b(?:box|field|input|bar)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the)\s+", "", name, flags=re.I).strip()
            return "searchbox", name or "search"
        if "textbox" in ql or "input" in ql or "field" in ql:
            name = re.sub(r"\b(?:textbox|input|field|box)\b", "", q, flags=re.I).strip()
            name = re.sub(r"^(?:the)\s+", "", name, flags=re.I).strip()
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
    def _parse_mcq_query(query: str) -> Dict[str, Any]:
        ql = query.lower().strip()
        
        # 1. Question number extraction: e.g. "Question 4", "Q4", "q.4", "question #3"
        q_match = re.search(r"\b(?:question|q|q\.)\s*#?\s*(\d+)\b", ql)
        q_num = int(q_match.group(1)) if q_match else None
        
        # Remove question part to isolate option
        rest = re.sub(r"\b(?:question|q|q\.)\s*#?\s*\d+\b", "", ql).strip()
        rest = re.sub(r"^(?:under|in|for|from|of)\b", "", rest).strip()

        # 2. Option letter extraction
        opt_letter = None
        # "option B", "choice B", "answer B"
        m_let = re.search(r"\b(?:option|choice|answer)\s*[:\-]?\s*([a-fA-F])\b", rest)
        if not m_let:
            # "B option", "B choice", "B answer"
            m_let = re.search(r"\b([a-fA-F])\s*(?:option|choice|answer)\b", rest)
        if not m_let:
            # "mark B", "circle B", "highlight B", or standalone "B"
            m_let = re.search(r"^(?:mark|circle|highlight|select|check|choose)?\s*([a-fA-F])\s*$", rest)
        if not m_let:
            # At end of string: "Question 4 B"
            m_let = re.search(r"\b([a-fA-F])$", rest)
            
        if m_let:
            opt_letter = m_let.group(1).upper()
            
        # 3. Token extraction for option text (e.g. "TCP", "UDP")
        clean_tokens = re.sub(r"\b(question|q|q\d+|option|choice|answer|select|mark|circle|highlight|click|check|choose|the|practice|mcq|this)\b", "", rest)
        tokens = [t.strip().lower() for t in clean_tokens.split() if len(t.strip()) > 1]
        
        is_mcq = (
            q_num is not None or
            opt_letter is not None or
            any(k in ql for k in ("option", "question", "radio", "choice", "answer", "mcq", "practice", "q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8"))
        )
        
        return {
            "is_mcq": is_mcq,
            "q_num": q_num,
            "opt_letter": opt_letter,
            "tokens": tokens,
            "raw": query
        }

    @staticmethod
    def _resolve_mcq_visual_target(page: Page, target: Any) -> Tuple[Optional[Locator], Dict[str, Any]]:
        """
        Dedicated resolver that returns the Locator for the COMPLETE VISIBLE answer option.
        Climbs from the radio input / label to the smallest visible container encompassing
        the radio button and option text.
        Never returns a tiny or hidden radio input.
        """
        JS_RESOLVE_VISUAL = """
        (function(el) {
          if (!el) return { found: false, isMcq: false };

          let radioEl = null;
          if (el.tagName === 'INPUT' && (el.type === 'radio' || el.type === 'checkbox')) {
            radioEl = el;
          } else if (el.getAttribute && (el.getAttribute('role') === 'radio' || el.getAttribute('role') === 'checkbox')) {
            radioEl = el;
          } else {
            radioEl = el.querySelector ? el.querySelector('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"]') : null;
            if (!radioEl && el.tagName === 'LABEL' && el.htmlFor) {
              radioEl = document.getElementById(el.htmlFor);
            }
            if (!radioEl && el.parentElement) {
              radioEl = el.parentElement.querySelector('input[type="radio"], input[type="checkbox"], [role="radio"], [role="checkbox"]');
            }
          }

          if (!radioEl) {
            const hasOptionClass = el.classList && Array.from(el.classList).some(c => /option|choice|answer/i.test(c));
            if (!hasOptionClass) return { found: false, isMcq: false };
          }

          let labelEl = null;
          if (radioEl && radioEl.id) {
            try { labelEl = document.querySelector('label[for="' + CSS.escape(radioEl.id) + '"]'); } catch(e){}
          }
          if (!labelEl && radioEl && radioEl.closest) {
            labelEl = radioEl.closest('label');
          }
          if (!labelEl && el.tagName === 'LABEL') {
            labelEl = el;
          }

          let bestContainer = null;
          let curr = (labelEl && radioEl && labelEl.contains(radioEl)) ? labelEl : (radioEl ? radioEl.parentElement : el);

          if (labelEl && radioEl && labelEl.contains(radioEl)) {
            const lr = labelEl.getBoundingClientRect();
            const lStyle = window.getComputedStyle(labelEl);
            if (lStyle.display !== 'none' && lStyle.visibility !== 'hidden' && lr.width > 20 && lr.height > 15) {
              bestContainer = labelEl;
            }
          }

          while (curr && curr !== document.body && curr !== document.documentElement) {
            if (radioEl && !curr.contains(radioEl)) {
              curr = curr.parentElement;
              continue;
            }

            const radiosInCurr = curr.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
            if (radiosInCurr.length > 1) {
              break;
            }

            const r = curr.getBoundingClientRect();
            const style = window.getComputedStyle(curr);
            const isVis = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && r.width > 5 && r.height > 5;

            if (isVis) {
              bestContainer = curr;
              if (r.width >= 50 && r.height >= 18) {
                const p = curr.parentElement;
                if (p && p !== document.body && p !== document.documentElement) {
                  const pRadios = p.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
                  if (pRadios.length === 1 && p.className && /option|choice|answer|item|row/i.test(p.className)) {
                    const pr = p.getBoundingClientRect();
                    if (pr.width >= r.width && pr.height >= r.height) {
                      bestContainer = p;
                    }
                  }
                }
                break;
              }
            }

            curr = curr.parentElement;
          }

          if (!bestContainer) {
            bestContainer = labelEl || (radioEl ? radioEl.parentElement : el);
          }
          if (!bestContainer) return { found: false, isMcq: false };

          let vr = bestContainer.getBoundingClientRect();
          if (vr.width <= 5 || vr.height <= 5) {
            let p = bestContainer.parentElement;
            while (p && p !== document.body && p !== document.documentElement) {
              const pr = p.getBoundingClientRect();
              if (pr.width > 10 && pr.height > 10) {
                bestContainer = p;
                vr = pr;
                break;
              }
              p = p.parentElement;
            }
          }

          const vUid = 'aurex_mcq_vis_' + Math.random().toString(36).substring(2, 9);
          bestContainer.setAttribute('data-aurex-mcq-vis', vUid);

          let rUid = null;
          if (radioEl) {
            rUid = 'aurex_mcq_radio_' + Math.random().toString(36).substring(2, 9);
            radioEl.setAttribute('data-aurex-mcq-radio', rUid);
          }

          return {
            found: true,
            isMcq: true,
            visualSelector: `[data-aurex-mcq-vis="${vUid}"]`,
            radioSelector: rUid ? `[data-aurex-mcq-radio="${rUid}"]` : null,
            visualTag: bestContainer.tagName,
            radioTag: radioEl ? radioEl.tagName : null,
            text: (bestContainer.innerText || bestContainer.textContent || '').trim().substring(0, 100),
            rect: {
              x: Math.round(vr.left),
              y: Math.round(vr.top),
              width: Math.round(vr.width),
              height: Math.round(vr.height)
            }
          };
        })
        """
        try:
            res = None
            if isinstance(target, Locator):
                res = target.evaluate(JS_RESOLVE_VISUAL)
            elif isinstance(target, str):
                loc = page.locator(target).first
                if loc.count() > 0:
                    res = loc.evaluate(JS_RESOLVE_VISUAL)
            elif target is not None:
                res = page.evaluate(JS_RESOLVE_VISUAL, target)

            if res and res.get("found") and res.get("isMcq"):
                vis_sel = res.get("visualSelector")
                if vis_sel:
                    v_loc = page.locator(vis_sel).first
                    if v_loc.count() > 0:
                        return v_loc, {
                            "source": "MCQ_VISUAL_TARGET",
                            "locator_str": vis_sel,
                            "visual_selector": vis_sel,
                            "radio_selector": res.get("radioSelector"),
                            "is_mcq": True,
                            "letter": res.get("letter"),
                            "option_text": res.get("text"),
                            "rect": res.get("rect"),
                            "visual_tag": res.get("visualTag"),
                            "radio_tag": res.get("radioTag")
                        }
        except Exception:
            pass

        return None, {}

    @staticmethod
    def _resolve_mcq_target(page: Page, query: str) -> Tuple[Optional[Locator], Dict[str, Any]]:
        """
        Specialized resolver for MCQ and Practice Question structures.
        Supports:
          - "option B", "B option", "answer B", "choice B", "B"
          - "option TCP", "answer TCP", "TCP option"
          - "Question 4 option B", "Q4 option B", "question 4 answer B"
          - "mark B", "circle B", "highlight B", "mark option B", "circle this answer"
        """
        parsed = TargetResolver._parse_mcq_query(query)
        if not parsed["is_mcq"]:
            return None, {}

        JS_MCQ_SEARCH = """
        (function(params) {
          const qNum = params.q_num;
          const optLetter = params.opt_letter ? params.opt_letter.toUpperCase() : null;
          const tokens = params.tokens || [];
          const rawQuery = (params.raw || '').toLowerCase();

          function resolveVisualContainer(radioEl, labelEl, fallbackEl) {
            let bestContainer = null;
            let curr = (labelEl && radioEl && labelEl.contains(radioEl)) ? labelEl : (radioEl ? radioEl.parentElement : fallbackEl);

            if (labelEl && radioEl && labelEl.contains(radioEl)) {
              const lr = labelEl.getBoundingClientRect();
              const lStyle = window.getComputedStyle(labelEl);
              if (lStyle.display !== 'none' && lStyle.visibility !== 'hidden' && lr.width > 20 && lr.height > 15) {
                bestContainer = labelEl;
              }
            }

            while (curr && curr !== document.body && curr !== document.documentElement) {
              if (radioEl && !curr.contains(radioEl)) {
                curr = curr.parentElement;
                continue;
              }

              const radiosInCurr = curr.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
              if (radiosInCurr.length > 1) {
                break;
              }

              const r = curr.getBoundingClientRect();
              const style = window.getComputedStyle(curr);
              const isVis = style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && r.width > 5 && r.height > 5;

              if (isVis) {
                bestContainer = curr;
                if (r.width >= 50 && r.height >= 18) {
                  const p = curr.parentElement;
                  if (p && p !== document.body && p !== document.documentElement) {
                    const pRadios = p.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
                    if (pRadios.length === 1 && p.className && /option|choice|answer|item|row/i.test(p.className)) {
                      const pr = p.getBoundingClientRect();
                      if (pr.width >= r.width && pr.height >= r.height) {
                        bestContainer = p;
                      }
                    }
                  }
                  break;
                }
              }

              curr = curr.parentElement;
            }

            if (!bestContainer) {
              bestContainer = labelEl || (radioEl ? radioEl.parentElement : fallbackEl);
            }

            let vr = bestContainer ? bestContainer.getBoundingClientRect() : { width: 0, height: 0, left: 0, top: 0 };
            if (vr.width <= 5 || vr.height <= 5) {
              let p = bestContainer ? bestContainer.parentElement : null;
              while (p && p !== document.body && p !== document.documentElement) {
                const pr = p.getBoundingClientRect();
                if (pr.width > 10 && pr.height > 10) {
                  bestContainer = p;
                  vr = pr;
                  break;
                }
                p = p.parentElement;
              }
            }

            return { container: bestContainer, rect: vr };
          }

          let searchScope = document.body;
          if (qNum !== null && qNum !== undefined) {
            const candidates = Array.from(document.querySelectorAll(
              'fieldset, [id*="question" i], [class*="question" i], [data-question], section, article, .card, div'
            ));
            let bestBlock = null;
            for (const b of candidates) {
              const text = (b.innerText || '').toLowerCase();
              const hasQ = text.includes('question ' + qNum) ||
                           text.includes('q' + qNum) ||
                           text.includes('q.' + qNum) ||
                           text.includes('question #' + qNum) ||
                           text.match(new RegExp('\\\\b' + qNum + '[\\\\.\\\\)]\\\\s+'));
              if (hasQ) {
                const radios = b.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
                if (radios.length > 0) {
                  if (!bestBlock || bestBlock.contains(b)) {
                    bestBlock = b;
                  }
                }
              }
            }

            if (!bestBlock) {
              const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, p, b, strong'));
              for (const h of headings) {
                const ht = (h.innerText || '').toLowerCase();
                if (ht.includes('question ' + qNum) || ht.includes('q' + qNum) || ht.match(new RegExp('\\\\b' + qNum + '[\\\\.\\\\)]\\\\s+'))) {
                  let parent = h.parentElement;
                  while (parent && parent !== document.body) {
                    const radios = parent.querySelectorAll('input[type="radio"], input[type="checkbox"], [role="radio"]');
                    if (radios.length > 0) {
                      bestBlock = parent;
                      break;
                    }
                    parent = parent.parentElement;
                  }
                  if (bestBlock) break;
                }
              }
            }

            if (bestBlock) {
              searchScope = bestBlock;
            }
          }

          let inputs = Array.from(searchScope.querySelectorAll(
            'input[type="radio"], input[type="checkbox"], [role="radio"]'
          ));
          if (inputs.length === 0) {
            inputs = Array.from(searchScope.querySelectorAll('[class*="option" i], [class*="choice" i], label'));
          }
          if (inputs.length === 0) return { found: false };

          const letterMap = { 'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5 };
          const targetIndex = optLetter ? letterMap[optLetter] : null;

          let bestMatch = null;
          let highestScore = -1;

          for (let i = 0; i < inputs.length; i++) {
            const el = inputs[i];
            let radio = (el.tagName === 'INPUT' || el.getAttribute('role') === 'radio') ? el : el.querySelector('input[type="radio"], input[type="checkbox"], [role="radio"]');
            if (!radio) radio = el;

            let label = null;
            if (radio && radio.id) {
              try { label = document.querySelector('label[for="' + CSS.escape(radio.id) + '"]'); } catch(e){}
            }
            if (!label && radio && radio.closest) {
              label = radio.closest('label');
            }
            if (!label && el.tagName === 'LABEL') {
              label = el;
            }

            const container = label ? (label.contains(radio) ? label : label.parentElement) : radio.parentElement;
            const text = (container ? (container.innerText || container.textContent) : (el.innerText || el.textContent || '')).trim();
            const textLower = text.toLowerCase();

            let score = 0;

            if (optLetter) {
              const letterRegex = new RegExp('^\\\\s*\\\\(?\\\\s*' + optLetter + '\\\\s*[\\\\)\\\\.\\\\:\\\\-\\\\s]', 'i');
              if (letterRegex.test(text)) {
                score += 100;
              } else if (container && container.querySelector) {
                const badge = container.querySelector('.letter, .choice, .badge, b, strong, [class*="letter" i]');
                if (badge && badge.innerText.trim().toUpperCase() === optLetter) {
                  score += 95;
                }
              }

              if (radio.value && radio.value.toUpperCase() === optLetter) {
                score += 85;
              }
              if (radio.id && radio.id.toUpperCase().endsWith('_' + optLetter.toLowerCase())) {
                score += 80;
              }
              if (targetIndex !== null && i === targetIndex) {
                score += 50;
              }
            }

            if (tokens.length > 0) {
              const matchesAll = tokens.every(t => textLower.includes(t));
              if (matchesAll) {
                score += 90;
              } else {
                const matchCount = tokens.filter(t => textLower.includes(t)).length;
                score += matchCount * 25;
              }
            }

            if (!optLetter && tokens.length === 0) {
              const vr = el.getBoundingClientRect();
              const vh = window.innerHeight;
              if (vr.top >= 0 && vr.bottom <= vh) {
                score += 40;
              } else {
                score += 20;
              }
            }

            if (score > highestScore && score >= 40) {
              highestScore = score;
              bestMatch = { radio: radio, label: label, el: el, text: text, index: i };
            }
          }

          if (!bestMatch) return { found: false };

          const res = resolveVisualContainer(bestMatch.radio, bestMatch.label, bestMatch.el);
          const visualEl = res.container;
          if (!visualEl) return { found: false };

          const vr = res.rect;
          const vUid = 'aurex_mcq_vis_' + Math.random().toString(36).substring(2, 9);
          visualEl.setAttribute('data-aurex-mcq-vis', vUid);

          let rUid = null;
          if (bestMatch.radio) {
            rUid = 'aurex_mcq_radio_' + Math.random().toString(36).substring(2, 9);
            bestMatch.radio.setAttribute('data-aurex-mcq-radio', rUid);
          }

          return {
            found: true,
            visualSelector: `[data-aurex-mcq-vis="${vUid}"]`,
            radioSelector: rUid ? `[data-aurex-mcq-radio="${rUid}"]` : null,
            visualTag: visualEl.tagName,
            radioTag: bestMatch.radio ? bestMatch.radio.tagName : null,
            letter: optLetter || (targetIndex !== null ? Object.keys(letterMap)[bestMatch.index] : null),
            text: bestMatch.text.substring(0, 100),
            rect: {
              x: Math.round(vr.left),
              y: Math.round(vr.top),
              width: Math.round(vr.width),
              height: Math.round(vr.height)
            }
          };
        })
        """

        try:
            res = page.evaluate(JS_MCQ_SEARCH, parsed)
            if res and res.get("found"):
                vis_sel = res.get("visualSelector")
                if vis_sel:
                    loc = page.locator(vis_sel).first
                    if loc.count() > 0:
                        return loc, {
                            "source": "MCQ_PRACTICE_DETECTOR",
                            "locator_str": vis_sel,
                            "visual_selector": vis_sel,
                            "radio_selector": res.get("radioSelector"),
                            "is_mcq": True,
                            "letter": res.get("letter"),
                            "option_text": res.get("text"),
                            "rect": res.get("rect"),
                            "visual_tag": res.get("visualTag"),
                            "radio_tag": res.get("radioTag")
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
            const title = (el.getAttribute('title') || '').toLowerCase();
            const testId = (el.getAttribute('data-testid') || el.getAttribute('data-qa') || el.getAttribute('data-cy') || '').toLowerCase();
            const role = (el.getAttribute('role') || el.tagName.toLowerCase());
            const id = (el.id || '').toLowerCase();
            const name = (el.getAttribute('name') || '').toLowerCase();

            let svgLabel = '';
            const svg = el.querySelector ? el.querySelector('svg') : null;
            if (svg) {
              svgLabel = (svg.getAttribute('aria-label') || svg.getAttribute('title') || svg.getAttribute('class') || '').toLowerCase();
            }

            let score = 0;

            for (const t of tokens) {
              if (text === t) score += 50;
              else if (text.includes(t)) score += 30;
              if (placeholder.includes(t)) score += 35;
              if (ariaLabel.includes(t)) score += 35;
              if (title.includes(t)) score += 35;
              if (testId.includes(t)) score += 35;
              if (svgLabel.includes(t)) score += 35;
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
            vlm_text = gemini.text([prompt, pil_img], tier=gemini.FAST, timeout_ms=8000) or ""
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
        if action in ("open", "navigate", "goto", "go", "visit"):
            url = target_query or text
            if not url:
                return False, "No URL provided to navigate.", metadata
            url = url.strip()
            if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("file:///"):
                if "." in url and " " not in url:
                    url = "https://" + url
                else:
                    url = f"https://www.google.com/search?q={url.replace(' ', '+')}"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                cdp._ensure_overlay_injected(page)
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action(action, url, "PLAYWRIGHT", "page.goto", "PASS", dur)
                return True, f"Navigated to: {page.title()} — {page.url}", metadata
            except Exception as e:
                return False, f"Navigation failed: {e}", metadata

        if action in ("back", "go_back"):
            try:
                page.go_back(timeout=6000)
                return True, f"Went back to: {page.title()} — {page.url}", metadata
            except Exception as e:
                return False, f"Could not navigate back: {e}", metadata

        if action in ("forward", "go_forward"):
            try:
                page.go_forward(timeout=6000)
                return True, f"Went forward to: {page.title()} — {page.url}", metadata
            except Exception as e:
                return False, f"Could not navigate forward: {e}", metadata

        if action in ("reload", "refresh"):
            page.reload(wait_until="domcontentloaded", timeout=15000)
            cdp._ensure_overlay_injected(page)
            return True, f"Reloaded: {page.title()}", metadata

        if action == "new_tab":
            new_p = cdp.new_tab(target_query or text)
            return True, f"Opened new tab: {new_p.title() or (target_query or 'blank')}", metadata

        if action == "switch_tab":
            ok, msg = cdp.switch_tab(target_query or text)
            return ok, msg, metadata

        if action in ("close_tab", "close tab"):
            tab_label = target_query or text
            pages = [p for p in cdp.context.pages if not p.is_closed()]
            closed = False
            for p in pages:
                try:
                    if not tab_label or tab_label.lower() in p.title().lower() or tab_label.lower() in p.url.lower():
                        title = p.title()
                        p.close()
                        closed = True
                        return True, f"Closed tab: '{title}'", metadata
                except Exception:
                    pass
            if not closed:
                return False, "No matching tab found to close.", metadata

        if action in ("list_tabs", "tabs", "show_tabs"):
            tabs = cdp.list_tabs()
            if not tabs:
                return True, "No open tabs found.", metadata
            lines = [f"Open Chrome Tabs ({len(tabs)}):"]
            for t in tabs:
                marker = " ◀ ACTIVE" if t["active"] else ""
                lines.append(f"  [{t['index']}] {t['title']} — {t['url'][:60]}{marker}")
            return True, "\n".join(lines), metadata

        if action in ("page_info", "current_tab", "current_page", "where", "url"):
            return True, f"Current page: {page.title()}\nURL: {page.url}", metadata

        # ── PAGE READING ──
        if action in ("read", "summary", "extract", "describe", "what_is_on_screen", "whats_on_page"):
            page_text = BrowserActionRouter._read_page_content(page)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("read", page.title(), "DOM_TEXT", "document.body.innerText", "PASS", dur)
            return True, page_text, metadata

        # ── SCREENSHOT / CAPTURE ──
        if action in ("screenshot", "capture", "snap", "take_screenshot"):
            try:
                import datetime
                save_dir = os.path.join(os.path.expanduser("~"), "Pictures", "AUREX Captures")
                os.makedirs(save_dir, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(save_dir, f"aurex_capture_{ts}.png")
                page.screenshot(path=filename, full_page=("full" in (target_query or "").lower()))
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action("screenshot", page.title(), "PLAYWRIGHT", "page.screenshot", "PASS", dur)
                return True, f"Screenshot saved to: {filename}", metadata
            except Exception as e:
                return False, f"Screenshot failed: {e}", metadata

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
            # Smart Find + Dynamic Scroll Loop: scroll down up to 3x, also try scrolling up once
            if action in ("click", "find", "highlight", "type", "fill", "copy", "clear", "hover"):
                # Try scrolling down to find
                for scroll_attempt in range(3):
                    BrowserScroller.smooth_scroll_direction(page, direction="down", amount=400)
                    loc, meta = TargetResolver.resolve_target(page, target_query, action_type=action)
                    if loc and loc.count() > 0:
                        break
                # If still not found, reset to top and try again
                if loc is None or loc.count() == 0:
                    try:
                        page.evaluate("window.scrollTo(0, 0)")
                        time.sleep(0.3)
                        loc, meta = TargetResolver.resolve_target(page, target_query, action_type=action)
                    except Exception:
                        pass

            if loc is None or loc.count() == 0:
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action(action, target_query, "DOM", "NOT_FOUND", "FAIL", dur)
                return False, f"Could not find '{target_query}' on '{page.title()}'. Try 'read' to see what's on this page.", metadata

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
            if meta.get("is_mcq"):
                pill_res = BrowserActionRouter._inject_pill_highlight(
                    page, loc, label="", duration_ms=5000, color="#10b981", is_mcq=True
                )
                pill_ok = bool(isinstance(pill_res, dict) and (pill_res.get("success") or pill_res.get("pillCreated")))
                r = pill_res.get("rect", {}) if isinstance(pill_res, dict) else {}
                radio_desc = meta.get("radio_tag") or "radio"
                vis_desc = meta.get("visual_tag") or "container"

                print(f"[MCQ] Radio target: {radio_desc}")
                print(f"[MCQ] Visual target: {vis_desc}")
                print(f"[MCQ] Rect: x={r.get('x', 0)} y={r.get('y', 0)} w={r.get('w', 0)} h={r.get('h', 0)}")
                print(f"[MCQ] Pill created: {'PASS' if pill_ok else 'FAIL'}")

                dur = int((time.time() - start_time) * 1000)
                if not pill_ok:
                    _log_chrome_action("highlight", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "FAIL", dur)
                    return False, f"Could not create visible AUREX pill around MCQ option '{target_query}'.", metadata

                _log_chrome_action("highlight", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
                letter = meta.get("letter")
                opt_str = f"option {letter}" if letter else f"'{target_query}'"
                return True, f"Highlighted {opt_str} with AUREX pill.", metadata
            else:
                BrowserActionRouter._inject_pill_highlight(page, loc, label="TARGET", duration_ms=4000)
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

        # ── CLEAR ──
        if action in ("clear", "erase", "delete_text"):
            BrowserActionRouter._inject_pill_highlight(page, loc, label="CLEAR", duration_ms=2000)
            try:
                loc.fill("")
            except Exception:
                try:
                    loc.click()
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                except Exception:
                    pass
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("clear", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Cleared text in '{target_query}'.", metadata

        # ── SELECT / DROPDOWN OPTION ──
        if action in ("select", "select_option", "choose") and not meta.get("is_mcq"):
            BrowserActionRouter._inject_pill_highlight(page, loc, label="SELECT", duration_ms=2500)
            opt_val = text or target_query
            selected = False
            try:
                is_sel = loc.evaluate("el => el.tagName === 'SELECT' || !!el.querySelector('select') || !!el.closest('select')")
                if is_sel:
                    target_sel = loc if loc.evaluate("el => el.tagName === 'SELECT'") else loc.locator("select").first
                    target_sel.select_option(label=opt_val)
                    selected = True
            except Exception:
                try:
                    target_sel.select_option(value=opt_val)
                    selected = True
                except Exception:
                    pass

            if selected:
                dur = int((time.time() - start_time) * 1000)
                _log_chrome_action("select_option", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
                return True, f"Selected '{opt_val}' in dropdown '{target_query}'.", metadata

        # ── TYPE / FILL ──
        if action in ("type", "fill", "write", "enter"):
            BrowserActionRouter._inject_pill_highlight(page, loc, label="TYPING", duration_ms=2500)
            
            # Check if target is contenteditable / rich editor (Discord, Slack, ChatGPT, Claude, etc.)
            is_rich = False
            try:
                is_rich = loc.evaluate("el => !!(el.isContentEditable || el.getAttribute('contenteditable') === 'true' || el.getAttribute('role') === 'textbox' || el.closest('[contenteditable=\"true\"]'))")
            except Exception:
                pass

            typed_ok = False
            if is_rich:
                try:
                    loc.click()
                    time.sleep(0.05)
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                    page.keyboard.insert_text(text)
                    typed_ok = True
                except Exception:
                    pass

            if not typed_ok:
                try:
                    loc.fill(text, timeout=3000)
                    typed_ok = True
                except Exception:
                    try:
                        loc.click()
                        loc.press_sequentially(text, delay=15)
                        typed_ok = True
                    except Exception:
                        try:
                            loc.focus()
                            page.keyboard.insert_text(text)
                            typed_ok = True
                        except Exception:
                            pass

            # Auto submit / press Enter if requested
            want_enter = (
                action == "enter" or
                "press enter" in target_query.lower() or
                "hit enter" in target_query.lower() or
                "and submit" in target_query.lower()
            )
            if want_enter:
                time.sleep(0.1)
                page.keyboard.press("Enter")

            # Verification
            val = ""
            try: val = loc.input_value()
            except Exception:
                try: val = loc.inner_text()
                except Exception: pass
            verif = "PASS" if (not text or text.lower() in (val or "").lower() or is_rich) else "VERIFY_WARNING"
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("type", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), verif, dur)
            res_msg = f"Entered '{text}' into '{target_query}'." + (" (Submitted with Enter)" if want_enter else "")
            return True, res_msg, metadata

        # ── PRACTICE / MCQ OPTION SELECTION (Requirement 25, 26) ──
        if meta.get("is_mcq") or action in ("check", "select_option", "mark", "circle"):
            # Resolve the underlying radio element for checking
            radio_loc = None
            if meta.get("radio_selector"):
                try:
                    radio_loc = page.locator(meta["radio_selector"]).first
                except Exception:
                    pass
            if not radio_loc or radio_loc.count() == 0:
                try:
                    r_cand = loc.locator('input[type="radio"], input[type="checkbox"], [role="radio"]').first
                    if r_cand.count() > 0:
                        radio_loc = r_cand
                except Exception:
                    pass
            if not radio_loc or radio_loc.count() == 0:
                radio_loc = loc

            try:
                radio_loc.check(timeout=2000)
            except Exception:
                try:
                    radio_loc.click(timeout=2000)
                except Exception:
                    try:
                        loc.click(timeout=2000)
                    except Exception:
                        pass

            # Verification of checked state
            is_checked = False
            try:
                is_checked = radio_loc.is_checked()
            except Exception:
                try:
                    is_checked = page.evaluate("el => !!(el.checked || el.getAttribute('aria-checked') === 'true')", radio_loc.element_handle())
                except Exception:
                    is_checked = True

            # Draw green rounded pill around the COMPLETE visible option
            pill_res = BrowserActionRouter._inject_pill_highlight(
                page, loc, label="", duration_ms=5000, color="#10b981", is_mcq=True
            )
            pill_ok = bool(isinstance(pill_res, dict) and (pill_res.get("success") or pill_res.get("pillCreated")))
            r = pill_res.get("rect", {}) if isinstance(pill_res, dict) else {}
            radio_desc = meta.get("radio_tag") or "INPUT (radio)"
            vis_desc = meta.get("visual_tag") or "CONTAINER"

            print(f"[MCQ] Radio target: {radio_desc}")
            print(f"[MCQ] Visual target: {vis_desc}")
            print(f"[MCQ] Rect: x={r.get('x', 0)} y={r.get('y', 0)} w={r.get('w', 0)} h={r.get('h', 0)}")
            print(f"[MCQ] Pill created: {'PASS' if pill_ok else 'FAIL'}")

            dur = int((time.time() - start_time) * 1000)
            if not pill_ok:
                _log_chrome_action("mcq_mark", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "FAIL", dur)
                return False, f"Could not create visible AUREX pill around MCQ option '{target_query}'.", metadata

            _log_chrome_action("mcq_mark", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS" if is_checked else "CLICKED", dur)
            letter = meta.get("letter")
            if letter:
                opt_display = f"option {letter}"
            elif meta.get("option_text"):
                opt_display = f"option '{meta.get('option_text')}'"
            else:
                opt_display = f"'{target_query}'"

            return True, f"Marked {opt_display} with AUREX pill.", metadata

        # ── CLICK / DOUBLE CLICK / RIGHT CLICK ──
        if action in ("click", "double_click", "right_click", "press", "tap"):
            # Animate AUREX visual pill around target first
            BrowserActionRouter._inject_pill_highlight(page, loc, label="CLICKING", duration_ms=1800)

            btn = "left"
            if click_type == "right" or action == "right_click":
                btn = "right"

            clicked = False
            try:
                if action == "double_click" or click_type == "double":
                    loc.dblclick(timeout=4000)
                else:
                    loc.click(button=btn, timeout=4000)
                clicked = True
            except Exception:
                # Fallback 1: force scroll into view then click
                try:
                    loc.scroll_into_view_if_needed(timeout=2000)
                    loc.click(button=btn, timeout=3000, force=True)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                # Fallback 2: JS dispatch click
                try:
                    loc.evaluate("el => { el.focus(); el.click(); }")
                    clicked = True
                except Exception as e_js:
                    dur = int((time.time() - start_time) * 1000)
                    _log_chrome_action(action, target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "FAIL", dur)
                    return False, f"Failed to click '{target_query}': {e_js}", metadata

            # Detect if click triggered navigation
            time.sleep(0.35)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action(action, target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            result_text = meta.get("text", target_query) or target_query
            return True, f"Clicked '{result_text}'.", metadata

        # ── HOVER ──
        if action == "hover":
            BrowserActionRouter._inject_pill_highlight(page, loc, label="HOVER", duration_ms=2500)
            try:
                loc.hover(timeout=3000)
            except Exception:
                loc.scroll_into_view_if_needed(timeout=1500)
                loc.hover(timeout=3000)
            dur = int((time.time() - start_time) * 1000)
            _log_chrome_action("hover", target_query, meta.get("source", "DOM"), meta.get("locator_str", ""), "PASS", dur)
            return True, f"Hovered over '{target_query}'.", metadata

        # ── FOCUS / ACTIVATE ──
        if action in ("focus", "activate", "select_all"):
            try:
                loc.focus(timeout=2500)
                if action == "select_all":
                    page.keyboard.press("Control+A")
            except Exception:
                loc.evaluate("el => el.focus()")
            BrowserActionRouter._inject_pill_highlight(page, loc, label="FOCUSED", duration_ms=2000)
            return True, f"Focused on '{target_query}'.", metadata

        # ── PRESS KEY / HOTKEY ──
        if action in ("press_key", "key", "hotkey"):
            key = (text or target_query).strip()
            # Normalize common key names
            key_norm = key.lower().replace(" ", "")
            key_map = {
                "enter": "Enter", "return": "Enter", "tab": "Tab", "escape": "Escape",
                "esc": "Escape", "space": "Space", "backspace": "Backspace", "delete": "Delete",
                "del": "Delete", "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft",
                "right": "ArrowRight", "home": "Home", "end": "End", "pageup": "PageUp",
                "pagedown": "PageDown", "f5": "F5", "f12": "F12",
                "ctrl+a": "Control+a", "ctrl+c": "Control+c", "ctrl+v": "Control+v",
                "ctrl+z": "Control+z", "ctrl+s": "Control+s", "ctrl+f": "Control+f",
                "ctrl+w": "Control+w", "ctrl+t": "Control+t", "ctrl+r": "Control+r",
                "ctrl+l": "Control+l", "ctrl+enter": "Control+Enter",
            }
            key_final = key_map.get(key_norm, key)
            page.keyboard.press(key_final)
            return True, f"Pressed key '{key_final}'.", metadata

        return False, f"Unsupported browser action: '{action}'.", metadata

    @staticmethod
    def _inject_pill_highlight(
        page: Page,
        locator: Locator,
        label: str = "AUREX",
        duration_ms: int = 3000,
        color: str = "#3b82f6",
        is_mcq: bool = False
    ) -> Dict[str, Any]:
        try:
            try:
                has_overlay = page.evaluate("() => typeof window.__aurex_highlight === 'function'")
                if not has_overlay:
                    page.evaluate(AUREX_OVERLAY_INJECTION_JS)
            except Exception:
                pass
            label_json = json.dumps(label)
            color_json = json.dumps(color)
            js_call = (
                f"el => window.__aurex_highlight ? window.__aurex_highlight(el, {label_json}, "
                f"{duration_ms}, {color_json}, 4, {str(is_mcq).lower()}) : {{ success: false, reason: 'NO_AUREX_FUNC' }}"
            )
            res = locator.evaluate(js_call)
            if isinstance(res, dict):
                return res
            return {"success": bool(res), "pillCreated": bool(res)}
        except Exception as e:
            return {"success": False, "pillCreated": False, "error": str(e)}

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
          const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4')).map(h => h.innerText.trim()).filter(Boolean);
          const paragraphs = Array.from(document.querySelectorAll('p, article, .content')).map(p => p.innerText.trim()).filter(p => p.length > 20).slice(0, 12);
          const inputs = Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"]'))
            .map(i => {
              const label = i.getAttribute('aria-label') || i.getAttribute('placeholder') || i.name || i.id || '';
              return label ? `${i.tagName.toLowerCase()}[${label}]` : '';
            }).filter(Boolean).slice(0, 8);
          const buttons = Array.from(document.querySelectorAll('button, a[role="button"], [role="button"]'))
            .map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(b => b.length > 1 && b.length < 30).slice(0, 10);
          return {
            title: title,
            url: url,
            headings: headings.slice(0, 10),
            paragraphs: paragraphs,
            inputs: inputs,
            buttons: buttons
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
            if data.get("buttons"):
                lines.append("\nKey Buttons: " + ", ".join(data["buttons"]))
            if data.get("inputs"):
                lines.append("Form Inputs: " + ", ".join(data["inputs"]))
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
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    try:
        import pyperclip
        pyperclip.copy(text)
    except Exception:
        pass


def _read_clipboard() -> str:
    if _WIN32:
        try:
            win32clipboard.OpenClipboard()
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return text or ""
        except Exception:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
    try:
        import pyperclip
        return pyperclip.paste() or ""
    except Exception:
        return ""


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
    def execute(
        action: str,
        target_query: str,
        text: str = "",
        direction: str = "down",
        click_type: str = "single"
    ) -> Tuple[bool, str]:
        print(f"[DESKTOP] Routing '{action} {target_query}' via Windows Desktop Automation...")
        action = action.lower().strip()

        # ── SCROLL ──
        if action == "scroll":
            dir_str = (direction or target_query or "down").lower()
            amount = 600 if dir_str == "up" else -600
            pyautogui.scroll(amount)
            return True, f"Scrolled desktop window {dir_str}."

        # ── PRESS KEY / HOTKEY ──
        if action in ("press_key", "key", "hotkey"):
            key_str = (text or target_query).strip()
            if "+" in key_str:
                keys = [k.strip().lower() for k in key_str.split("+")]
                pyautogui.hotkey(*keys)
                return True, f"Pressed hotkey: {'+'.join(keys)}"
            elif key_str:
                pyautogui.press(key_str.lower())
                return True, f"Pressed key: {key_str}"

        # ── READ SCREEN VIA OCR ──
        if action in ("read", "extract", "summary"):
            ocr_text = DesktopFallbackRouter._read_desktop_ocr()
            if ocr_text:
                if len(ocr_text) > 1500:
                    ocr_text = ocr_text[:1500] + "\n...[truncated]"
                return True, f"Desktop Screen Content:\n{ocr_text}"
            return False, "Could not extract text from current desktop screen."

        # ── TYPE WITHOUT TARGET QUERY ──
        if action in ("type", "fill", "write") and not target_query:
            pyautogui.write(text, interval=0.02)
            if action == "enter" or "press enter" in (text or "").lower():
                pyautogui.press("enter")
            return True, f"Typed text into active desktop window: '{text}'"

        # ── LOCATE TARGET POINT (COORDINATES / RELATIVE POSITION / UIA / OCR / VISION) ──
        target_pt = None
        sw, sh = pyautogui.size()
        tq = (target_query or "").strip()

        # 1. Direct Coordinate parsing: e.g. "(500, 300)", "500, 300", "x=500 y=300", "500 300"
        m_coord = re.search(r"\(?\s*(\d{1,5})\s*[,x\s]\s*(\d{1,5})\s*\)?", tq)
        if m_coord:
            try:
                cx = int(m_coord.group(1))
                cy = int(m_coord.group(2))
                if 0 <= cx <= sw and 0 <= cy <= sh:
                    target_pt = (cx, cy)
            except Exception:
                pass

        # 2. Relative Percentages: e.g. "50%, 50%", "50% 50%"
        if not target_pt and "%" in tq:
            m_pct = re.search(r"(\d{1,3})%\s*[,x\s]\s*(\d{1,3})%", tq)
            if m_pct:
                target_pt = (int(int(m_pct.group(1)) / 100.0 * sw), int(int(m_pct.group(2)) / 100.0 * sh))

        # 3. Named screen positions
        if not target_pt:
            tq_lower = tq.lower()
            if tq_lower in ("center", "middle", "center of screen", "middle of screen", "screen center"):
                target_pt = (sw // 2, sh // 2)
            elif "top left" in tq_lower:
                target_pt = (int(sw * 0.15), int(sh * 0.15))
            elif "top right" in tq_lower:
                target_pt = (int(sw * 0.85), int(sh * 0.15))
            elif "bottom left" in tq_lower:
                target_pt = (int(sw * 0.15), int(sh * 0.85))
            elif "bottom right" in tq_lower:
                target_pt = (int(sw * 0.85), int(sh * 0.85))
            elif "top center" in tq_lower or "top middle" in tq_lower:
                target_pt = (sw // 2, int(sh * 0.15))
            elif "bottom center" in tq_lower or "bottom middle" in tq_lower:
                target_pt = (sw // 2, int(sh * 0.85))

        # 4. Fallback for empty target or "here" / "current"
        if not target_pt and tq_lower in ("", "here", "current", "screen", "this"):
            target_pt = pyautogui.position()

        # 5. Locate via Windows UI Automation (active foreground window first)
        if not target_pt and tq:
            target_pt = DesktopFallbackRouter._find_uia_element(tq)

        # 6. Locate via Local WinRT OCR
        if not target_pt and tq and _WINRT_OCR:
            target_pt = DesktopFallbackRouter._find_ocr_word(tq)

        # 7. Locate via AI Vision Grounding (sees icons, buttons, thumbnails, visual targets)
        if not target_pt and tq:
            target_pt = DesktopFallbackRouter._find_desktop_vision_point(tq)

        # ── COPY ACTION ──
        if action == "copy":
            if target_pt:
                pyautogui.moveTo(target_pt[0], target_pt[1], duration=0.15)
                pyautogui.doubleClick()
                time.sleep(0.1)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.1)
            copied = _read_clipboard()
            return True, f"Copied desktop content to clipboard: '{copied}'"

        if not target_pt:
            return False, f"Could not locate '{target_query}' on the screen. Try providing coordinates or screen area."

        cx, cy = target_pt
        if action in ("click", "double_click", "right_click", "press", "tap"):
            pyautogui.moveTo(cx, cy, duration=0.15)
            if action == "double_click" or click_type == "double":
                pyautogui.doubleClick()
            elif action == "right_click" or click_type == "right":
                pyautogui.rightClick()
            else:
                pyautogui.click()
            target_label = target_query or f"position ({cx}, {cy})"
            return True, f"Clicked '{target_label}' at ({cx}, {cy}) on screen."

        if action in ("type", "fill", "write", "enter"):
            pyautogui.moveTo(cx, cy, duration=0.15)
            pyautogui.click()
            time.sleep(0.1)
            pyautogui.write(text, interval=0.02)
            if action == "enter" or "press enter" in target_query.lower() or "hit enter" in target_query.lower():
                pyautogui.press("enter")
            return True, f"Clicked and typed '{text}' into '{target_query}'."

        if action == "hover":
            pyautogui.moveTo(cx, cy, duration=0.2)
            return True, f"Hovered over '{target_query}' at ({cx}, {cy})."

        return False, f"Unsupported desktop action: '{action}'."

    @staticmethod
    def _find_desktop_vision_point(query: str) -> Optional[Tuple[int, int]]:
        """
        Visual Grounding on the real desktop screen using Gemini Vision.
        Captures the screen and asks Gemini for normalized coordinates of the target.
        Works for icons, video thumbnails, buttons without text, play buttons, images, etc.
        """
        if not _MSS or not _PIL:
            return None
        try:
            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

            sw, sh = pyautogui.size()
            img.thumbnail((1280, 720), Image.Resampling.BILINEAR)

            prompt = (
                f"You are a computer screen grounding engine. The user wants to click or interact with: '{query}'.\n"
                f"Find the location of '{query}' on this screen.\n"
                f"Return ONLY valid JSON: {{\"found\": true, \"x\": <0-1000>, \"y\": <0-1000>}} where x and y are "
                f"normalized coordinates from 0 to 1000 representing the center of '{query}'.\n"
                f"If not found on screen, return: {{\"found\": false}}"
            )
            vlm_text = gemini.text([prompt, img], tier=gemini.FAST, timeout_ms=8000)
            if not vlm_text:
                return None
            clean_json = re.sub(r"^```[a-zA-Z]*\n?", "", vlm_text.strip())
            clean_json = re.sub(r"\n?```$", "", clean_json).strip()
            data = json.loads(clean_json)

            if data.get("found") and "x" in data and "y" in data:
                cx = int((float(data["x"]) / 1000.0) * sw)
                cy = int((float(data["y"]) / 1000.0) * sh)
                print(f"[VISION_GROUNDING] Located '{query}' at desktop coordinates ({cx}, {cy})")
                return (cx, cy)
        except Exception as e:
            print(f"[VISION_GROUNDING_ERROR] {e}")
        return None

    @staticmethod
    def _read_desktop_ocr() -> str:
        if not _WINRT_OCR or not _MSS:
            return ""
        import asyncio
        try:
            with mss.mss() as sct:
                mon = sct.monitors[0]
                shot = sct.grab(mon)
                png_bytes = mss.tools.to_png(shot.rgb, shot.size)

            async def _ocr():
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
                return "\n".join(line.text for line in res.lines if line.text.strip())

            return asyncio.run(_ocr())
        except Exception:
            return ""

    @staticmethod
    def _find_uia_element(query: str) -> Optional[Tuple[int, int]]:
        if not _PYWINAUTO:
            return None
        clean = query.lower().strip()
        try:
            desktop = PywinDesktop(backend="uia")
            
            # Prioritize active foreground window first for instant speed and accuracy
            foreground_win = None
            try:
                import win32gui
                hwnd = win32gui.GetForegroundWindow()
                if hwnd:
                    foreground_win = desktop.window(handle=hwnd)
            except Exception:
                pass

            windows_to_check = []
            if foreground_win:
                try:
                    if foreground_win.is_visible():
                        windows_to_check.append(foreground_win)
                except Exception:
                    pass

            for win in desktop.windows():
                try:
                    if win.is_visible() and (not foreground_win or win.handle != foreground_win.handle):
                        windows_to_check.append(win)
                except Exception:
                    continue

            for win in windows_to_check:
                try:
                    for ctrl in win.descendants():
                        try:
                            ctrl_name = getattr(ctrl.element_info, "name", "") or ""
                            win_text = ctrl.window_text() or ""
                            auto_id = getattr(ctrl.element_info, "automation_id", "") or ""
                            haystack = f"{ctrl_name} {win_text} {auto_id}".lower()
                            if clean in haystack and ctrl.is_visible():
                                rect = ctrl.rectangle()
                                if rect.width() > 0 and rect.height() > 0:
                                    return (rect.mid_point().x, rect.mid_point().y)
                        except Exception:
                            continue
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

                # 1. Search full line text for phrase match (multi-word support)
                for line in res.lines:
                    line_text = line.text.lower()
                    if clean_q in line_text:
                        matching_words = [w for w in line.words if w.text.lower() in clean_q or any(token in w.text.lower() for token in clean_q.split())]
                        if matching_words:
                            min_x = min(w.bounding_rect.x for w in matching_words)
                            min_y = min(w.bounding_rect.y for w in matching_words)
                            max_x = max(w.bounding_rect.x + w.bounding_rect.width for w in matching_words)
                            max_y = max(w.bounding_rect.y + w.bounding_rect.height for w in matching_words)
                            return (int((min_x + max_x) / 2), int((min_y + max_y) / 2))
                        r = line.bounding_rect
                        return (int(r.x + r.width / 2), int(r.y + r.height / 2))

                # 2. Token overlap or individual word match
                tokens = [t for t in clean_q.split() if len(t) > 1]
                for line in res.lines:
                    for w in line.words:
                        w_low = w.text.lower()
                        if clean_q == w_low or (tokens and all(tok in line.text.lower() for tok in tokens) and any(tok in w_low for tok in tokens)):
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
    action = (action or "").lower().strip()
    target = (target or "").lower().strip()
    text = (text or "").lower().strip()
    combined = f"{action} {target} {text}"

    # Browser navigation actions always go to Chrome
    if action in (
        "open", "navigate", "goto", "go", "visit",
        "new_tab", "switch_tab", "close_tab", "list_tabs", "tabs", "show_tabs",
        "back", "go_back", "forward", "go_forward", "reload", "refresh",
        "screenshot", "capture", "snap", "take_screenshot",
        "page_info", "current_tab", "current_page", "where", "url",
        "read", "summary", "extract", "describe", "what_is_on_screen",
    ):
        return True

def is_chrome_target(action: str, target_query: str, text: str) -> bool:
    action = (action or "").lower().strip()
    target = (target_query or "").lower().strip()
    combined = f"{action} {target} {text}".lower()

    # Browser navigation commands always go to browser
    if action in ("open", "navigate", "goto", "visit", "switch_tab", "new_tab", "close_tab", "list_tabs"):
        return True

    # URL patterns always go to Chrome
    if any(target.startswith(p) for p in ("http://", "https://", "www.", "file://")) or any(s in target for s in (".com", ".org", ".io", ".net", ".edu", ".gov")):
        return True

    # If Chrome CDP is ALREADY alive and connected to a real page, use it
    cdp = ChromeCDPManager.get_instance()
    if cdp.is_alive():
        try:
            if cdp.active_page and not cdp.active_page.is_closed():
                u = cdp.active_page.url or ""
                if u and not u.startswith("about:"):
                    return True
        except Exception:
            pass

    # Only route to browser if user explicitly asks for Chrome / browser
    if "in chrome" in combined or "in browser" in combined:
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
            if ok:
                if explain:
                    return f"{msg}\n[Chrome Engine | Source: {meta.get('source', 'DOM')} | Locator: {meta.get('locator_str', 'N/A')}]"
                return msg
            else:
                print(f"[CHROME] Target '{target_query}' not resolved via Chrome DOM ({msg}). Falling back to desktop screen automation...")
        except Exception as e:
            print(f"[CHROME_ERROR] Falling back to desktop automation: {e}")
            pass

    # Desktop Fallback (UIA + OCR + Coordinates + Vision Grounding)
    ok, msg = DesktopFallbackRouter.execute(
        action=action,
        target_query=target_query,
        text=text,
        direction=direction,
        click_type=click_type
    )
    return msg


# ── 9. AUREX PLUGIN SPECIFICATION & RUN HANDLER ───────────────────────────────

PLUGIN = {
    "name": "screencntrl",
    "description": (
        "AUREX Chrome-native computer use & screen understanding agent. "
        "Operates directly on Chrome's DOM, accessibility tree, and real semantic page structure via CDP/Playwright. "
        "Can click, type, scroll, copy, fill forms, navigate, mark MCQ options, capture screenshots, and read page content. "
        "Examples: 'click Login', 'type my email into email field', 'scroll down', 'scroll to heading Features', "
        "'open youtube.com', 'highlight option B', 'mark option TCP', 'what is on this page', 'take a screenshot', "
        "'click the first button', 'press ctrl+c', 'clear search box', 'switch to Gmail tab', 'close this tab', "
        "'list all open tabs', 'click close button', 'double click the image', 'hover over profile'. "
        "Uses animated AUREX visual pill overlays for element targeting feedback. "
        "Falls back to Windows UIA + WinRT OCR for non-browser desktop apps."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "The action to perform. Supported values: "
                    "click | double_click | right_click | tap | type | fill | clear | erase | "
                    "copy | scroll | hover | focus | find | highlight | read | describe | "
                    "open | navigate | back | forward | reload | screenshot | capture | "
                    "switch_tab | new_tab | close_tab | list_tabs | page_info | "
                    "press_key | hotkey | mark | circle | select_option | check | select_all"
                )
            },
            "target": {
                "type": "STRING",
                "description": (
                    "Natural language element or page target description. Examples: "
                    "'Login button', 'blue button', 'search box', 'email field', 'first link', "
                    "'second option', 'last item', 'Question 4 option B', 'option TCP', "
                    "'section called Installation', 'close button', 'YouTube tab', 'this', 'that'"
                )
            },
            "text": {
                "type": "STRING",
                "description": "Text to type/fill for type actions, URL for open/navigate actions, or key name for press_key (e.g. 'Enter', 'Escape', 'ctrl+s')"
            },
            "direction": {
                "type": "STRING",
                "description": "Scroll direction: up | down | left | right"
            },
            "click_type": {
                "type": "STRING",
                "description": "Click type: single | double | right"
            },
            "highlight": {
                "type": "BOOLEAN",
                "description": "Whether to show an animated AUREX visual pill overlay around the detected target element"
            },
            "explain": {
                "type": "BOOLEAN",
                "description": "Return debug grounding details showing how the element was resolved"
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
