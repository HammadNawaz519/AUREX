"""Web search and browser automation tools for AUREX."""

import webbrowser
import urllib.request
import urllib.parse
import json
import re
from typing import Dict, Any, Optional
from app.tools.base import BaseTool, ToolResult


class OpenUrlTool(BaseTool):
    name = "open_url"
    description = "Open a website URL in the user's default web browser."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The web address to open"}
        },
        "required": ["url"]
    }
    is_write = False

    def execute(self, url: str, **kwargs) -> ToolResult:
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://")):
            clean_url = "https://" + clean_url
        try:
            webbrowser.open(clean_url)
            return ToolResult(success=True, message=f"Opening {clean_url}")
        except Exception as e:
            return ToolResult(success=False, error=f"Could not open URL: {e}")


class SearchWebTool(BaseTool):
    name = "search_web"
    description = "Search the internet for questions, documentation, news, or tutorials."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"]
    }
    is_write = False

    def execute(self, query: str, **kwargs) -> ToolResult:
        try:
            # Query DuckDuckGo Instant Answer API
            encoded = urllib.parse.quote_plus(query)
            api_url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(api_url, headers={"User-Agent": "Aurex/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            answer = data.get("AbstractText") or data.get("Answer")
            if not answer and data.get("RelatedTopics"):
                for topic in data["RelatedTopics"]:
                    if isinstance(topic, dict) and topic.get("Text"):
                        answer = topic["Text"]
                        break

            if answer:
                return ToolResult(success=True, data=answer, message=answer)

            # If instant answer is empty, open browser with search query
            search_page = f"https://www.google.com/search?q={encoded}"
            webbrowser.open(search_page)
            return ToolResult(success=True, message=f"Opened web search for '{query}' in browser.")
        except Exception as e:
            # Fallback to opening browser directly
            try:
                encoded = urllib.parse.quote_plus(query)
                webbrowser.open(f"https://www.google.com/search?q={encoded}")
                return ToolResult(success=True, message=f"Opened search for '{query}'.")
            except Exception as e2:
                return ToolResult(success=False, error=f"Search failed: {e2}")
