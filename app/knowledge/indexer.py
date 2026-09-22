"""Local project and documentation knowledge indexer for AUREX.

Scans and indexes approved directories (e.g., D:\\Projects, D:\\AUREX\\knowledge)
for code, READMEs, Markdown, PDF, and config files entirely locally without cloud transmission.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from app.memory.database import get_db
from app.config.settings import get_settings
from app.core.security import is_path_allowed, canonical_path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".py", ".md", ".txt", ".json", ".csv", ".c", ".cpp",
    ".h", ".hpp", ".java", ".rs", ".go", ".html", ".css", ".yaml", ".yml"
}


class KnowledgeIndexer:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(KnowledgeIndexer, cls).__new__(cls)
            cls._instance._db = get_db()
        return cls._instance

    def index_directory(self, dir_path: str, max_files: int = 150) -> int:
        """Scan and index text, documentation, and code files inside an approved directory."""
        allowed, reason = is_path_allowed(dir_path, is_write=False)
        if not allowed:
            logger.warning(f"Skipping index: {reason}")
            return 0

        root = Path(dir_path)
        if not root.exists() or not root.is_dir():
            return 0

        indexed_count = 0
        conn = self._db.get_connection()

        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # Skip hidden folders, node_modules, git
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "vendor", "__pycache__", "venv", ".venv")]

                for fname in filenames:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS or "readme" in fname.lower():
                        full_path = os.path.join(dirpath, fname)
                        try:
                            # Limit reading to 200KB per file for speed
                            size = os.path.getsize(full_path)
                            if size > 250 * 1024:
                                continue

                            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                                content = f.read(50000)

                            summary = self._extract_summary(fname, content)
                            chunks = json.dumps([content[:2000]])

                            with conn:
                                conn.execute(
                                    "INSERT INTO knowledge_docs (file_path, file_name, file_type, summary, content_chunks, updated_at) "
                                    "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                                    "ON CONFLICT(file_path) DO UPDATE SET summary=excluded.summary, content_chunks=excluded.content_chunks, updated_at=CURRENT_TIMESTAMP",
                                    (full_path, fname, ext or "file", summary, chunks)
                                )
                            indexed_count += 1
                            if indexed_count >= max_files:
                                break
                        except Exception as e:
                            continue

                if indexed_count >= max_files:
                    break
        finally:
            conn.close()

        logger.info(f"Indexed {indexed_count} local documents from {dir_path}")
        return indexed_count

    def _extract_summary(self, fname: str, content: str) -> str:
        """Extract high-level overview of symbols, classes, or markdown headings."""
        lines = content.splitlines()
        headings = [l.strip("# ").strip() for l in lines if l.startswith("# ")][:3]
        if headings:
            return f"Topic: {', '.join(headings)}"

        defs = re.findall(r"(?:def|class)\s+([a-zA-Z0-9_]+)", content)[:5]
        if defs:
            return f"Contains: {', '.join(defs)}"

        # First line of text
        for line in lines:
            clean = line.strip()
            if clean and not clean.startswith(("/*", "//", "<!--")):
                return clean[:120]
        return f"File: {fname}"

    def search_local_knowledge(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search indexed local documentation and code files."""
        clean_q = query.lower().strip()
        words = [w for w in re.findall(r"\b\w+\b", clean_q) if len(w) > 2]
        if not words:
            return []

        conn = self._db.get_connection()
        try:
            # Query documents where file name or content chunks match
            rows = conn.execute("SELECT file_path, file_name, file_type, summary, content_chunks FROM knowledge_docs").fetchall()
            matches = []

            for r in rows:
                score = 0
                fn = r["file_name"].lower()
                summary = (r["summary"] or "").lower()
                chunks = (r["content_chunks"] or "").lower()

                for w in words:
                    if w in fn:
                        score += 5
                    if w in summary:
                        score += 3
                    if w in chunks:
                        score += 1

                if score > 0:
                    matches.append({
                        "file_path": r["file_path"],
                        "file_name": r["file_name"],
                        "summary": r["summary"],
                        "score": score
                    })

            matches.sort(key=lambda x: x["score"], reverse=True)
            return matches[:limit]
        finally:
            conn.close()

    def index_all(self) -> int:
        """Scan and index all directories defined in settings.knowledge_directories."""
        settings = get_settings()
        total = 0
        for d in settings.knowledge_directories:
            total += self.index_directory(d)
        return total


_global_indexer = KnowledgeIndexer()

def get_knowledge_indexer() -> KnowledgeIndexer:
    return _global_indexer

def get_indexer() -> KnowledgeIndexer:
    return _global_indexer

