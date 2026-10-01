"""
file_processor.py — JARVIS Universal File Processor (fixed)

KEY BEHAVIOUR
  * READS files silently — it never launches an app window.
  * FINDS files from spoken / vague addresses: "D drive, folder college, file lecture notes dot pdf".
    If it is not sure, it returns NEED_INFO and asks, instead of guessing.
  * Reports success only when the output file was checked on disk (VERIFIED / FAILED).

Supported types (default action is "read" = return the content as text):
  image   → read(OCR+describe), describe, ocr, resize, convert, compress, crop, rotate, info
  pdf     → read, summarize, extract_text, extract_pages, to_word, info
  docx/doc/rtf/odt → read, summarize, extract_text, reformat, fix, translate, word_count, to_pdf
  txt/md/log/ini… → read, summarize, reformat, fix, translate, word_count
  csv/tsv → read, analyze, filter, sort, convert, stats, info
  xlsx/xls/ods → read (all sheets), analyze, filter, sort, convert, stats, info
  json/xml/svg → read, validate, format, analyze, to_csv
  code    → read, explain, review, fix, optimize, document, test, run, info
  audio   → read(transcribe), transcribe, trim, convert, info
  video   → read(info+transcript), trim, extract_audio, extract_frame, compress, convert, info
  zip/tar/gz/7z → read(list), list, extract, (member=… reads one file inside without extracting)
  pptx/ppt/odp → read, summarize, extract_text, analyze, to_pdf
  sqlite/db → read (tables + sample rows), query (SELECT only)
  anything else → sniffed: text is read as text, binary gets a safe summary + readable strings
"""

import os
import re
import io
import sys
import json
import time
import gzip
import html
import shutil
import sqlite3
import zipfile
import tarfile
import tempfile
import platform
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET

# Model choice, timeout and fallback ladder all live in core/gemini.py.
from core import gemini

# Reuse the file controller's path helpers when available (same Desktop/OneDrive logic).
try:
    from actions.file_controller import (
        _resolve_path as _fc_resolve,
        _search_roots as _fc_roots,
        _is_safe_path as _fc_safe,
    )
except Exception:
    _fc_resolve = _fc_roots = _fc_safe = None

_OS = platform.system()
_LAST_FILE: Path | None = None          # lets "summarize it" / "that file" work
_DEFAULT_READ_CHARS = 8000
_MAX_READ_BYTES = 20 * 1024 * 1024

_SKIP_DIRS = {"windows", "program files", "program files (x86)", "programdata", "appdata",
              "node_modules", "$recycle.bin", "system volume information", "__pycache__",
              "site-packages", "venv", ".venv", ".git"}


def set_uploaded_file(path) -> None:
    """Call this from the UI when the user drops/uploads a file so an empty file_path works."""
    global _LAST_FILE
    _LAST_FILE = Path(str(path))


# ═════════════════════════════════════════════════════════════════════════════
#  small helpers
# ═════════════════════════════════════════════════════════════════════════════

def _need(msg: str) -> str:
    return f"NEED_INFO: {msg} Ask the user this question and wait for the answer. Do NOT guess."


def _flag(params: dict, key: str, default: bool) -> bool:
    v = params.get(key, default)
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "")
    return bool(v)


def _file_size_str(path: Path) -> str:
    size = path.stat().st_size
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.1f} GB"


def _output_path(src: Path, suffix: str, new_ext: str = None) -> Path:
    """Unique output path next to the source (never overwrites an existing file)."""
    ext = new_ext or src.suffix
    folder = src.parent
    if not os.access(folder, os.W_OK):
        folder = Path(tempfile.gettempdir())
    out = folder / f"{src.stem}_{suffix}{ext}"
    n = 2
    while out.exists():
        out = folder / f"{src.stem}_{suffix}_{n}{ext}"
        n += 1
    return out


def _save_text(out: Path, text: str) -> bool:
    try:
        out.write_text(text, encoding="utf-8")
        return out.is_file() and out.stat().st_size > 0
    except Exception:
        return False


def _done(out: Path, msg: str) -> str:
    """Only claim success after checking the output really exists."""
    try:
        if out.is_file() and out.stat().st_size > 0:
            return f"VERIFIED: {msg} Saved: {out.resolve()}"
    except Exception:
        pass
    return f"FAILED: {msg} — but the output file was not found at {out}."


def _deliver(result: str, path: Path, action: str, params: dict) -> str:
    """Long AI answers are saved next to the file (verified) and previewed."""
    if len(result) > 600 and _flag(params, "save", True):
        out = _output_path(path, re.sub(r"\W+", "_", action) or "result", ".txt")
        if _save_text(out, result):
            return f"{result[:400]}...\n\nVERIFIED: full result saved: {out.resolve()}"
    return result


def _to_seconds(v, default: float = 0.0) -> float:
    if v in (None, ""):
        return default
    s = str(v).strip()
    if ":" in s:
        sec = 0.0
        for p in s.split(":"):
            sec = sec * 60 + float(p)
        return sec
    return float(s)


def _page(text: str, params: dict) -> str:
    """Return a slice of text so huge files can be read in pages."""
    try:
        offset = max(int(params.get("offset") or 0), 0)
    except Exception:
        offset = 0
    try:
        limit = max(int(params.get("max_chars") or _DEFAULT_READ_CHARS), 200)
    except Exception:
        limit = _DEFAULT_READ_CHARS
    chunk = text[offset:offset + limit]
    end = offset + len(chunk)
    if end < len(text):
        chunk += (f"\n\n[Showing characters {offset}-{end} of {len(text)}. "
                  f"Call again with offset={end} to continue.]")
    elif offset:
        chunk += f"\n\n[End of file — characters {offset}-{end} of {len(text)}.]"
    return chunk


# ═════════════════════════════════════════════════════════════════════════════
#  AI helpers
# ═════════════════════════════════════════════════════════════════════════════

def _ask(contents) -> str:
    resp = gemini.call(contents, tier=gemini.SMART, timeout_ms=90000)
    if resp is None:
        raise RuntimeError("every Gemini model on the ladder failed")
    text = getattr(resp, "text", None)
    if not text or not str(text).strip():
        raise RuntimeError("the AI returned no text")
    return str(text).strip()


def _ai_over_text(task: str, body: str) -> str:
    """Runs a task over text of any length (long text is processed in parts)."""
    limit, part = 40000, 30000
    if len(body) <= limit:
        return _ask(f"{task}\n\n{body}")
    chunks = [body[i:i + part] for i in range(0, len(body), part)]
    note = ""
    if len(chunks) > 8:
        note = f"\n\n[Note: only the first {8 * part} characters of {len(body)} were processed.]"
        chunks = chunks[:8]
    partial = []
    for i, c in enumerate(chunks, 1):
        partial.append(_ask(f"{task}\n(This is part {i} of {len(chunks)} of a longer document; "
                            f"cover only this part.)\n\n{c}"))
    final = _ask("Combine these partial results into ONE coherent final answer for this task: "
                 f"{task}\n\n" + "\n\n".join(partial))
    return final + note


# ═════════════════════════════════════════════════════════════════════════════
#  FINDING THE FILE  (spoken addresses, fuzzy names, all drives)
# ═════════════════════════════════════════════════════════════════════════════

_DRIVE_RE = re.compile(
    r"^(?:(?:in|on|inside|the)\s+)*(?:(?:drive\s+([a-z]))|(?:([a-z])\s*(?::|\s+drive)))\s*[:/\\]?\s*(.*)$",
    re.I)
_FILLER_RE = re.compile(r"\b(?:folder|directory|called|named|inside|the|in|on|at|then)\b", re.I)


def _clean_spoken(s) -> str:
    """Turn voice-transcribed text into a path-like string."""
    s = str(s or "").strip().strip('"').strip("'").strip()
    if not s:
        return ""
    s = re.sub(r"\s+(?:back\s?slash|forward\s?slash|slash)\s+", "/", s, flags=re.I)
    s = re.sub(r"^([a-z])\s+colon\s*", r"\1:/", s, flags=re.I)
    s = re.sub(r"\s+dot\s+([a-z0-9]{1,5})\s*$", r".\1", s, flags=re.I)
    return s


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _basic_resolve(raw: str) -> Path:
    raw = str(raw or "").strip().strip('"').strip("'")
    home = Path.home()
    low = raw.lower().replace("\\", "/").strip("/")
    sc = {"desktop": home / "Desktop", "downloads": home / "Downloads",
          "documents": home / "Documents", "pictures": home / "Pictures",
          "music": home / "Music", "videos": home / "Videos", "home": home}
    if low in sc:
        return sc[low]
    m = _DRIVE_RE.match(raw.replace("\\", "/"))
    if m and not m.group(3).strip():
        return Path(f"{(m.group(1) or m.group(2)).upper()}:/")
    return Path(raw).expanduser()


def _try_resolve(raw: str):
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        return _fc_resolve(raw) if _fc_resolve else _basic_resolve(raw)
    except Exception:
        return None


def _roots() -> list:
    roots = []
    if _fc_roots:
        try:
            roots = list(_fc_roots())
        except Exception:
            roots = []
    if not roots:
        home = Path.home()
        roots = [Path.cwd(), home / "Desktop", home / "Downloads", home / "Documents"]
        if _OS == "Windows":
            roots += [Path(f"{c}:/") for c in "DEFGHIJ"]
    roots.append(Path.home())
    out, seen = [], set()
    for r in roots:
        try:
            k = os.path.normcase(str(r.resolve()))
        except Exception:
            k = os.path.normcase(str(r))
        if k not in seen and r.exists():
            seen.add(k)
            out.append(r)
    return out


def _iter_files(roots, deadline):
    """Yield (dirpath, filename, root_index). Each folder is visited once."""
    seen = set()
    for idx, root in enumerate(roots):
        for dp, dns, fns in os.walk(root):
            if time.time() > deadline:
                return
            k = os.path.normcase(os.path.abspath(dp))
            if k in seen:
                dns[:] = []
                continue
            seen.add(k)
            dns[:] = [d for d in dns if not d.startswith((".", "$")) and d.lower() not in _SKIP_DIRS]
            for fn in fns:
                if fn.startswith((".", "~$")):
                    continue
                yield dp, fn, idx


def _name_score(filename: str, qname: str, qext: str, qk: str, toks: list) -> int:
    low = filename.lower()
    fext = Path(filename).suffix.lower()
    if qext and fext != qext:
        return 0
    if low == qname.lower():
        return 100
    skey = _key(Path(filename).stem)
    if qk and skey == qk:
        return 90
    if qk and skey.startswith(qk):
        return 75
    if qk and qk in skey:
        return 65
    fk = _key(low)
    if toks and all(t in fk for t in toks):
        return 55
    return 0


def _search_name(name: str, roots, cap: float = 15.0, limit: int = 300) -> list:
    """Fuzzy filename search. Returns [(score, root_idx, Path)] best first."""
    name = name.strip()
    m = re.search(r"(\.[A-Za-z][A-Za-z0-9]{0,4})$", name)

    def run(qname, qext, qstem):
        qk = _key(qstem)
        toks = re.findall(r"[a-z0-9]+", qstem.lower())
        if not qk:
            return []
        found, seen = [], set()
        deadline = time.time() + cap
        for dp, fn, idx in _iter_files(roots, deadline):
            sc = _name_score(fn, qname, qext, qk, toks)
            if sc:
                p = Path(dp) / fn
                k = os.path.normcase(str(p))
                if k not in seen:
                    seen.add(k)
                    found.append((sc, idx, p))
                    if len(found) >= limit:
                        break
        return found

    res = []
    if m:
        res = run(name, m.group(1).lower(), name[:-len(m.group(1))])
    if not res:
        res = run(name, "", name)
    res.sort(key=lambda t: (-t[0], t[1], len(str(t[2]))))
    return res


def _find_folders(hint: str, cap: float = 10.0) -> list:
    """Resolve a spoken folder description to real folders (best matches)."""
    hint = _clean_spoken(hint)
    if not hint:
        return []
    p = _try_resolve(hint)
    try:
        if p and p.is_dir():
            return [p]
    except Exception:
        pass

    h = hint.replace("\\", "/")
    letter, rest = None, h
    m = _DRIVE_RE.match(h)
    if m:
        letter = (m.group(1) or m.group(2)).upper()
        rest = m.group(3)
    rest = _FILLER_RE.sub(" ", rest).strip(" /")

    if letter:
        base = Path(f"{letter}:/")
        if not base.exists():
            return []
        if not rest:
            return [base]
        direct = base / rest
        try:
            if direct.is_dir():
                return [direct]
        except Exception:
            pass
        bases = [base]
    else:
        bases = _roots()

    key = _key(rest)
    if not key:
        return []
    deadline = time.time() + cap
    best, best_score, seen = [], 0, set()
    for base in bases:
        bdepth = len(base.parts)
        for dp, dns, _ in os.walk(base):
            if time.time() > deadline:
                break
            dns[:] = [d for d in dns if not d.startswith((".", "$")) and d.lower() not in _SKIP_DIRS]
            dpp = Path(dp)
            if len(dpp.parts) - bdepth >= 6:
                dns[:] = []
            nk = os.path.normcase(os.path.abspath(dp))
            if nk in seen:
                dns[:] = []
                continue
            seen.add(nk)
            rel = dpp.parts[bdepth:]
            if not rel:
                continue
            last = _key(rel[-1])
            if len(last) < 2 or last not in key:
                continue
            score = sum(len(k) for k in (_key(x) for x in rel) if len(k) >= 2 and k in key)
            if score / max(len(key), 1) < 0.5:
                continue
            if score > best_score:
                best, best_score = [dpp], score
            elif score == best_score:
                best.append(dpp)
    return best


def _list_dir_for_user(d: Path, limit: int = 30) -> str:
    items = []
    try:
        for it in sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if it.name.startswith("."):
                continue
            items.append(f"  {len(items) + 1}. {'📁 ' if it.is_dir() else '📄 '}{it.name}")
            if len(items) >= limit:
                items.append("  ...")
                break
    except Exception:
        pass
    return "\n".join(items)


def _locate(params: dict):
    """Returns (Path, note) when found, or (None, NEED_INFO/err message)."""
    raw_path = _clean_spoken(next((params.get(k) for k in ("file_path", "path", "filepath", "target", "file")
                                   if params.get(k)), ""))
    name = _clean_spoken(next((params.get(k) for k in ("name", "filename", "file_name") if params.get(k)), ""))
    folder = _clean_spoken(next((params.get(k) for k in ("folder", "directory", "location", "dir")
                                 if params.get(k)), ""))

    if not (raw_path or name or folder):
        if _LAST_FILE is not None and _LAST_FILE.exists():
            return _LAST_FILE, f"(Using the last file: {_LAST_FILE})"
        return None, _need("Which file do you want me to read, and which drive/folder is it in?")

    # 1. a complete, valid path
    if raw_path:
        p = _try_resolve(raw_path)
        try:
            if p and p.is_file():
                return p, ""
            if p and p.is_dir():
                folder = folder or str(p)
            else:
                rp = raw_path.replace("\\", "/")
                if name:
                    folder = folder or raw_path          # path was really the folder
                elif "/" in rp:
                    head, _, tail = rp.rstrip("/").rpartition("/")
                    name, folder = tail, (folder or head)
                else:
                    name = raw_path
        except Exception:
            name = name or raw_path

    # 2. folder + name joined directly
    dirs = []
    if folder:
        fp = _try_resolve(folder)
        try:
            if fp and fp.is_dir() and name and (fp / name).is_file():
                return fp / name, ""
        except Exception:
            pass
        dirs = _find_folders(folder)
        if not dirs:
            return None, _need(f"I could not find a folder matching '{folder}'. Which drive and folder is it in? "
                               f"Or should I search every drive for the file name?")
        if name:
            for d in dirs:
                try:
                    if (d / name).is_file():
                        return d / name, ""
                except Exception:
                    pass

    # 3. folder only → ask which file
    if not name:
        if len(dirs) > 1:
            listing = "\n".join(f"  {i + 1}. {d}" for i, d in enumerate(dirs[:10]))
            return None, _need(f"Several folders match '{folder}':\n{listing}\nWhich one?")
        d = dirs[0]
        files = [x for x in d.iterdir() if x.is_file() and not x.name.startswith(".")]
        if not files:
            return None, _need(f"The folder '{d}' has no files directly inside. Contents:\n"
                               f"{_list_dir_for_user(d)}\nWhich sub-folder or file?")
        return None, _need(f"'{d}' contains:\n{_list_dir_for_user(d)}\nWhich file should I read?")

    # 4. fuzzy name search (inside the folder hint, else everywhere)
    cands = _search_name(name, dirs if dirs else _roots())
    if not cands and dirs:
        return None, _need(f"I looked inside {', '.join(str(d) for d in dirs[:3])} but found no file matching "
                           f"'{name}'. What is the exact file name, or should I search all drives?")
    if not cands:
        return None, _need(f"I searched Desktop, Downloads, Documents and all drives but found no file like '{name}'. "
                           f"Which folder is it in, or what is the exact name?")

    top = cands[0][0]
    tops = [c for c in cands if c[0] == top]
    if len(cands) == 1 or (len(tops) == 1 and top >= 75):
        p = cands[0][2]
        note = "" if top >= 90 else f"(Matched '{name}' to '{p.name}')"
        return p, note
    listing = "\n".join(f"  {i + 1}. {c[2]}" for i, c in enumerate(cands[:10]))
    return None, _need(f"I found {len(cands)} files that could match '{name}':\n{listing}\nWhich one?")


# ═════════════════════════════════════════════════════════════════════════════
#  type detection
# ═════════════════════════════════════════════════════════════════════════════

def _detect_type(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    image_exts = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "tif", "ico", "heic", "heif"}
    video_exts = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v", "3gp"}
    audio_exts = {"mp3", "wav", "ogg", "m4a", "aac", "flac", "wma", "opus"}
    code_exts = {"py", "js", "ts", "jsx", "tsx", "html", "htm", "css", "java", "c", "cpp", "cs", "go",
                 "rs", "rb", "php", "swift", "kt", "sh", "bash", "ps1", "bat", "cmd", "lua", "r", "m",
                 "sql", "yaml", "yml", "toml", "h", "hpp", "vue", "scss", "ipynb"}
    archive_exts = {"zip", "rar", "tar", "gz", "tgz", "7z", "bz2", "xz"}
    text_exts = {"txt", "md", "rst", "log", "ini", "cfg", "conf", "env", "tex", "srt", "vtt", "jsonl",
                 "ndjson", "properties", "text", "readme"}
    xml_exts = {"xml", "svg", "xsl", "rss", "kml", "plist", "xaml"}

    if ext in image_exts: return "image"
    if ext in video_exts: return "video"
    if ext in audio_exts: return "audio"
    if ext in code_exts: return "code"
    if ext in archive_exts: return "archive"
    if ext == "pdf": return "pdf"
    if ext in ("docx", "doc"): return "docx"
    if ext in ("odt", "odp", "ods"): return "odf"
    if ext == "rtf": return "rtf"
    if ext == "epub": return "epub"
    if ext in text_exts: return "text"
    if ext in ("csv", "tsv"): return "csv"
    if ext in ("xlsx", "xls", "xlsm", "ods"): return "excel"
    if ext == "json": return "json"
    if ext in xml_exts: return "xml"
    if ext in ("pptx", "ppt"): return "pptx"
    if ext in ("db", "sqlite", "sqlite3"): return "sqlite"
    return "unknown"


def _looks_text(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            data = f.read(8192)
    except Exception:
        return False
    if not data:
        return True
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    printable = sum(1 for b in data if b in (9, 10, 13) or 32 <= b < 127 or b >= 128)
    return printable / len(data) > 0.92


# ═════════════════════════════════════════════════════════════════════════════
#  READING every kind of file as text (no app is ever opened)
# ═════════════════════════════════════════════════════════════════════════════

def _read_text_file(path: Path) -> str:
    data = path.read_bytes()[:_MAX_READ_BYTES]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _soffice_path():
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if exe:
        return exe
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
              r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if os.path.exists(p):
            return p
    return None


def _soffice_convert(path: Path, target_ext: str, outdir: Path = None) -> Path:
    exe = _soffice_path()
    if not exe:
        raise RuntimeError("LibreOffice (soffice) is not installed, needed for this conversion.")
    outdir = outdir or Path(tempfile.mkdtemp(prefix="jarvis_conv_"))
    r = subprocess.run([exe, "--headless", "--convert-to", target_ext, "--outdir", str(outdir), str(path)],
                       capture_output=True, text=True, timeout=180, errors="replace")
    out = outdir / f"{path.stem}.{target_ext.split(':')[0]}"
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"LibreOffice conversion failed: {(r.stderr or r.stdout)[-200:]}")
    return out


def _strings_from_bytes(data: bytes, limit: int = 200) -> str:
    found = re.findall(rb"[\x20-\x7e]{6,}", data)[:limit]
    return "\n".join(s.decode("ascii", "ignore") for s in found)


def _read_docx(path: Path) -> str:
    if path.suffix.lower() == ".doc":
        try:
            return _read_docx(_soffice_convert(path, "docx"))
        except Exception as e:
            return ("[Old .doc format — could not convert cleanly (" + str(e) + "). "
                    "Readable text fragments:]\n" + _strings_from_bytes(path.read_bytes()[:3_000_000]))
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        raise RuntimeError("python-docx not installed. Run: pip install python-docx")
    doc = Document(str(path))
    out = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(Paragraph(child, doc).text)
        elif tag == "tbl":
            for row in Table(child, doc).rows:
                out.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(out)


def _read_pptx(path: Path) -> str:
    if path.suffix.lower() == ".ppt":
        return _read_pptx(_soffice_convert(path, "pptx"))
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("python-pptx not installed. Run: pip install python-pptx")
    prs = Presentation(str(path))

    def walk(shapes, acc):
        for sh in shapes:
            if getattr(sh, "shapes", None) is not None and sh.shape_type == 6:   # group
                walk(sh.shapes, acc)
                continue
            if getattr(sh, "has_text_frame", False) and sh.text_frame.text.strip():
                acc.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    acc.append(" | ".join(c.text.strip() for c in row.cells))

    out = []
    for i, slide in enumerate(prs.slides, 1):
        acc = []
        walk(slide.shapes, acc)
        block = f"--- Slide {i} ---\n" + "\n".join(acc)
        try:
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                block += "\n[Notes] " + slide.notes_slide.notes_text_frame.text.strip()
        except Exception:
            pass
        out.append(block)
    return "\n\n".join(out)


def _read_odf(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", "replace")
    xml = re.sub(r"</text:(?:p|h)>", "\n", xml)
    xml = re.sub(r"</table:table-cell>", " | ", xml)
    xml = re.sub(r"</table:table-row>", "\n", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def _read_rtf(path: Path) -> str:
    raw = _read_text_file(path)
    try:
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(raw)
    except Exception:
        pass
    t = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "ignore"), raw)
    t = re.sub(r"\\par[d]?", "\n", t)
    t = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", t)
    return re.sub(r"[{}]", "", t)


def _read_epub(path: Path) -> str:
    out = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith((".xhtml", ".html", ".htm")):
                t = z.read(n).decode("utf-8", "replace")
                t = re.sub(r"<(script|style).*?</\1>", "", t, flags=re.S | re.I)
                t = re.sub(r"</(p|div|h\d|li|br)>", "\n", t, flags=re.I)
                out.append(html.unescape(re.sub(r"<[^>]+>", "", t)))
    return "\n".join(out)


def _pdf_pages(path: Path) -> list:
    errors = []

    def via_fitz():
        import fitz
        with fitz.open(str(path)) as d:
            return [pg.get_text() for pg in d]

    def via_pypdf():
        try:
            import pypdf as m
        except ImportError:
            import PyPDF2 as m
        r = m.PdfReader(str(path))
        if getattr(r, "is_encrypted", False):
            r.decrypt("")
        return [(pg.extract_text() or "") for pg in r.pages]

    def via_plumber():
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            return [(p.extract_text() or "") for p in pdf.pages]

    got_pages = None
    for fn in (via_fitz, via_pypdf, via_plumber):
        try:
            pages = fn()
            got_pages = pages
            if any(p.strip() for p in pages):
                return pages
        except Exception as e:
            errors.append(f"{fn.__name__}: {e}")
    if got_pages is not None:
        return got_pages              # readable PDF but no text (scanned)
    raise RuntimeError("Could not read the PDF. Install one: pip install pymupdf pypdf pdfplumber. "
                       "Details: " + "; ".join(errors))


def _parse_pages(spec, n: int) -> list:
    idx = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            a = int(a or 1)
            b = int(b or n)
            idx.extend(range(a, min(b, n) + 1))
        else:
            if 1 <= int(part) <= n:
                idx.append(int(part))
    return sorted(set(i for i in idx if 1 <= i <= n))


def _read_pdf(path: Path, params: dict) -> str:
    pages = _pdf_pages(path)
    sel = range(1, len(pages) + 1)
    if params.get("pages"):
        sel = _parse_pages(params["pages"], len(pages))
        if not sel:
            raise RuntimeError(f"The PDF has {len(pages)} pages; none match '{params['pages']}'.")
    text = "".join(f"--- Page {i} ---\n{pages[i - 1]}\n\n" for i in sel)
    if text.replace("-", "").replace("Page", "").strip() and any(pages[i - 1].strip() for i in sel):
        return text
    # scanned PDF → let the AI read it directly
    if path.stat().st_size <= 18 * 1024 * 1024:
        try:
            return _ask(["Extract ALL text from this scanned document, keeping page order. "
                         "Return only the text.", {"mime_type": "application/pdf", "data": path.read_bytes()}])
        except Exception as e:
            return f"(This PDF has no text layer (scanned) and AI reading failed: {e})"
    return "(This PDF has no text layer (scanned) and is too large for AI reading.)"


def _load_tables(path: Path, ftype: str) -> dict:
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas not installed. Run: pip install pandas openpyxl")
    if ftype == "csv":
        last = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                if path.suffix.lower() == ".tsv":
                    df = pd.read_csv(path, sep="\t", encoding=enc, nrows=500000)
                else:
                    try:
                        df = pd.read_csv(path, sep=None, engine="python", encoding=enc, nrows=500000)
                    except UnicodeDecodeError:
                        raise
                    except Exception:
                        df = pd.read_csv(path, encoding=enc, nrows=500000)
                return {"data": df}
            except UnicodeDecodeError as e:
                last = e
        raise RuntimeError(f"Could not decode CSV: {last}")
    try:
        return pd.read_excel(path, sheet_name=None)
    except Exception as e:
        if path.suffix.lower() in (".xls", ".ods") and _soffice_path():
            conv = _soffice_convert(path, "xlsx")
            return pd.read_excel(conv, sheet_name=None)
        hint = " (for .xls run: pip install xlrd; for .ods: pip install odfpy)" if path.suffix.lower() in (".xls", ".ods") else ""
        raise RuntimeError(f"Could not read spreadsheet: {e}{hint}")


def _df_text(df, rows: int = 50) -> str:
    return (f"Shape: {len(df)} rows × {len(df.columns)} columns\n"
            f"Columns: {', '.join(map(str, df.columns))}\n\n{df.head(rows).to_string(max_cols=30)}")


def _archive_entries(path: Path) -> list:
    """[(name, size)]"""
    ext = path.suffix.lower()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            return [(i.filename, i.file_size) for i in z.infolist()]
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            return [(m.name, m.size) for m in t.getmembers()]
    if ext == ".7z":
        import py7zr
        with py7zr.SevenZipFile(path) as z:
            return [(i.filename, i.uncompressed) for i in z.list()]
    if ext == ".gz":
        return [(path.stem, 0)]
    raise RuntimeError(f"Unsupported archive format: {ext} (for .7z: pip install py7zr)")


def _archive_member_text(path: Path, member: str) -> str:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            hit = next((n for n in names if n == member), None) or \
                next((n for n in names if member.lower() in n.lower()), None)
            if not hit:
                raise RuntimeError(f"'{member}' is not inside the archive.")
            data = z.read(hit)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            m = next((x for x in t.getmembers() if member.lower() in x.name.lower() and x.isfile()), None)
            if not m:
                raise RuntimeError(f"'{member}' is not inside the archive.")
            data = t.extractfile(m).read()
    else:
        raise RuntimeError("Reading a single member is supported for zip and tar archives.")
    if b"\x00" in data[:4096]:
        return f"[Binary file inside archive, {len(data)} bytes]\n" + _strings_from_bytes(data)
    return data.decode("utf-8", "replace")


def _sqlite_summary(path: Path, query: str = "") -> str:
    uri = path.resolve().as_uri() + "?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.cursor()
        if query:
            if not query.strip().lower().startswith(("select", "pragma table_info", "with")):
                raise RuntimeError("Only read-only SELECT queries are allowed.")
            cur.execute(query)
            cols = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(50)
            return " | ".join(cols) + "\n" + "\n".join(" | ".join(map(str, r)) for r in rows)
        tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        out = [f"SQLite database with {len(tables)} table(s)."]
        for t in tables[:20]:
            n = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            cur.execute(f'SELECT * FROM "{t}" LIMIT 5')
            cols = [d[0] for d in cur.description]
            out.append(f"\n[{t}] {n} rows. Columns: {', '.join(cols)}")
            for r in cur.fetchall():
                out.append("  " + " | ".join(map(str, r)))
        return "\n".join(out)
    finally:
        con.close()


_MAGIC = [(b"%PDF", "PDF document"), (b"PK\x03\x04", "ZIP-based container (zip/Office/jar)"),
          (b"MZ", "Windows executable / DLL"), (b"\x89PNG", "PNG image"), (b"GIF8", "GIF image"),
          (b"\xff\xd8\xff", "JPEG image"), (b"7z\xbc\xaf", "7-Zip archive"), (b"Rar!", "RAR archive"),
          (b"SQLite format 3", "SQLite database"), (b"ID3", "MP3 audio"), (b"RIFF", "RIFF (wav/avi/webp)"),
          (b"OggS", "Ogg media"), (b"fLaC", "FLAC audio"), (b"\x1f\x8b", "GZIP data"),
          (b"\x7fELF", "ELF executable")]


def _binary_summary(path: Path) -> str:
    data = path.read_bytes()[:2_000_000]
    kind = next((d for m, d in _MAGIC if data.startswith(m)), "Unknown binary data")
    s = _strings_from_bytes(data, 60)
    return (f"Binary file: {kind}, {_file_size_str(path)}. This type has no direct text content.\n"
            + (f"\nReadable text fragments:\n{s}" if s else ""))


def _extract_text(path: Path, ftype: str, params: dict) -> str:
    """Return the readable content of ANY file as text. Never launches an application."""
    if ftype in ("text", "code", "xml", "unknown"):
        return _read_text_file(path)
    if ftype == "json":
        raw = _read_text_file(path)
        try:
            return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
        except Exception:
            return raw
    if ftype == "pdf":
        return _read_pdf(path, params)
    if ftype == "docx":
        return _read_docx(path)
    if ftype == "pptx":
        return _read_pptx(path)
    if ftype == "odf":
        return _read_odf(path)
    if ftype == "rtf":
        return _read_rtf(path)
    if ftype == "epub":
        return _read_epub(path)
    if ftype in ("csv", "excel"):
        tables = _load_tables(path, ftype)
        parts = []
        for name, df in tables.items():
            parts.append(f"=== Sheet: {name} ===\n{_df_text(df, int(params.get('rows') or 50))}")
        return "\n\n".join(parts)
    if ftype == "archive":
        if params.get("member"):
            return _archive_member_text(path, str(params["member"]))
        ents = _archive_entries(path)
        lines = [f"Archive contains {len(ents)} entries:"]
        lines += [f"  {n}  ({s} B)" for n, s in ents[:80]]
        if len(ents) > 80:
            lines.append(f"  ... and {len(ents) - 80} more")
        return "\n".join(lines)
    if ftype == "sqlite":
        return _sqlite_summary(path, str(params.get("query") or ""))
    if ftype == "image":
        return _image_ai(path, "read", params)
    if ftype == "audio":
        return _transcribe(path, path, params, save=False)
    if ftype == "video":
        info = _video_info(path)
        try:
            tr = _video_transcript(path, params)
        except Exception as e:
            tr = f"(No transcript: {e})"
        return f"{info}\n\nTranscript:\n{tr}"
    if ftype == "binary":
        return _binary_summary(path)
    return _read_text_file(path)


def _read_any(path: Path, ftype: str, params: dict) -> str:
    text = _extract_text(path, ftype, params)
    if not str(text).strip():
        return f"File: {path}\n(No readable text found in this file.)"
    return f"File: {path} ({ftype}, {_file_size_str(path)})\n\n" + _page(str(text), params)


# ═════════════════════════════════════════════════════════════════════════════
#  universal text actions (summarize / fix / translate / custom instruction …)
# ═════════════════════════════════════════════════════════════════════════════

_TASKS = {
    "summarize": "Summarize this {kind} concisely.",
    "summary": "Summarize this {kind} concisely.",
    "analyze": "Analyze this {kind} thoroughly: key points, structure and notable details.",
    "reformat": "Reformat this {kind} cleanly with proper structure, headings and paragraphs.",
    "fix": "Fix grammar, spelling and style issues and return the corrected version.",
    "to_bullet": "Convert this {kind} into a clear bullet-point summary.",
    "translate_hint": "What language is this {kind} in and what does it say? Summarize.",
    "explain": "Explain this {kind} clearly.",
    "review": "Review this {kind} for bugs, issues and improvements.",
    "optimize": "Optimize this {kind} for performance and readability and return the full result.",
    "document": "Add proper documentation/comments to this {kind} and return the full result.",
    "test": "Write unit tests for this {kind}.",
}


def _basic_info(path: Path, ftype: str) -> str:
    st = path.stat()
    mod = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    return f"{path.name}: type={ftype}, size={_file_size_str(path)}, modified={mod}, location={path.parent}"


def _universal(path: Path, ftype: str, action: str, params: dict) -> str:
    if action == "info":
        return _basic_info(path, ftype)
    text = _extract_text(path, ftype, params)
    if not str(text).strip():
        return "The file has no readable text."
    text = str(text)

    if action == "word_count":
        return f"{len(text.split())} words, {len(text)} characters, {text.count(chr(10)) + 1} lines."
    if action == "extract_text":
        if ftype in ("text", "code"):
            return _page(text, params)
        out = _output_path(path, "text", ".txt")
        _save_text(out, text)
        return _done(out, f"Text extracted ({len(text)} chars).")

    instruction = (params.get("instruction") or "").strip()
    kind = "code" if ftype == "code" else "document"
    if action == "translate":
        lang = params.get("language") or instruction or "English"
        task = f"Translate this {kind} into {lang}. Return only the translation."
    elif action in _TASKS:
        task = _TASKS[action].format(kind=kind)
        if instruction:
            task += f" Additional instruction: {instruction}"
    else:
        task = instruction or action

    body = f"```{path.suffix.lstrip('.')}\n{text}\n```" if ftype == "code" else text
    result = _ai_over_text(task, body)

    if ftype == "code" and action in ("fix", "optimize", "document") and _flag(params, "save", True):
        out = _output_path(path, action)
        mt = re.search(r"```(?:\w+)?\n(.*?)```", result, re.DOTALL)
        _save_text(out, mt.group(1) if mt else result)
        return f"{result[:400]}...\n\n" + _done(out, "Result saved.")
    return _deliver(result, path, action, params)


# ═════════════════════════════════════════════════════════════════════════════
#  per-type handlers
# ═════════════════════════════════════════════════════════════════════════════

# ── image ────────────────────────────────────────────────────────────────────

def _image_ai(path: Path, action: str, params: dict) -> str:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
    prompts = {
        "read": "Extract all text visible in this image exactly as written, preserving layout. "
                "Then on a new line starting with 'Description:' describe the image briefly.",
        "describe": "Describe this image in detail.",
        "ocr": "Extract all text visible in this image. Return only the text, formatted clearly.",
        "analyze": "Analyze this image thoroughly: objects, colors, composition, any text, context.",
        "extract_text": "Extract all text from this image.",
    }
    prompt = (params.get("instruction") or "").strip() or prompts.get(action) or action
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img.thumbnail((2400, 2400))
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    try:
        return _ask([prompt, img])
    except Exception as e:
        if action in ("read", "ocr", "extract_text"):
            try:
                import pytesseract
                txt = pytesseract.image_to_string(img)
                if txt.strip():
                    return txt.strip()
            except Exception:
                pass
        raise RuntimeError(f"AI image analysis failed: {e}")


def _process_image(path: Path, action: str, params: dict, speak=None) -> str:
    try:
        from PIL import Image
    except ImportError:
        return "Pillow is not installed. Run: pip install Pillow"
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass

    action = action or "read"
    geo = {"resize", "convert", "compress", "crop", "rotate", "info"}

    if action not in geo:
        try:
            return _deliver(_image_ai(path, action, params), path, action, params)
        except Exception as e:
            return f"FAILED: {e}"

    try:
        img = Image.open(path)
        if action == "info":
            return (f"Image info: {img.format}, {img.size[0]}x{img.size[1]}px, "
                    f"mode: {img.mode}, size: {_file_size_str(path)}")

        if action == "resize":
            width = int(params.get("width") or 0)
            height = int(params.get("height") or 0)
            scale = float(params.get("scale") or 0)
            w, h = img.size
            if scale:
                new = (max(int(w * scale), 1), max(int(h * scale), 1))
            elif width and height:
                new = (width, height)
            elif width:
                new = (width, max(int(h * width / w), 1))
            elif height:
                new = (max(int(w * height / h), 1), height)
            else:
                return _need("What size should the image be? (width, height, or a scale like 0.5)")
            out = _output_path(path, f"resized_{new[0]}x{new[1]}")
            img.resize(new, Image.LANCZOS).save(out)
            return _done(out, f"Resized from {w}x{h} to {new[0]}x{new[1]}.")

        if action == "convert":
            fmt = str(params.get("format") or "").lower().strip(".")
            if not fmt:
                return _need("Which format should I convert the image to? (png, jpg, webp, bmp, tiff)")
            fmt_map = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP",
                       "bmp": "BMP", "tiff": "TIFF", "ico": "ICO", "gif": "GIF"}
            pil_fmt = fmt_map.get(fmt, fmt.upper())
            if pil_fmt == "JPEG" and img.mode != "RGB":
                img = img.convert("RGB")
            out = _output_path(path, "converted", f".{fmt}")
            img.save(out, pil_fmt)
            return _done(out, f"Converted to {fmt.upper()}.")

        if action == "compress":
            quality = min(max(int(params.get("quality") or 70), 1), 95)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, (255, 255, 255))
                bg.paste(rgba, mask=rgba.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            out = _output_path(path, f"compressed_q{quality}", ".jpg")
            img.save(out, "JPEG", quality=quality, optimize=True)
            return _done(out, f"Compressed: {_file_size_str(path)} → {_file_size_str(out)}.")

        if action == "crop":
            try:
                box = tuple(int(params[k]) for k in ("left", "top", "right", "bottom"))
            except Exception:
                return _need("Which region should I crop? Give left, top, right and bottom in pixels.")
            out = _output_path(path, "cropped")
            img.crop(box).save(out)
            return _done(out, f"Cropped to {box}.")

        if action == "rotate":
            angle = float(params.get("angle") or 90)
            out = _output_path(path, f"rotated_{int(angle)}")
            img.rotate(angle, expand=True).save(out)
            return _done(out, f"Rotated {angle:g}°.")
    except Exception as e:
        return f"FAILED: image {action} failed: {e}"
    return "Done."


# ── pdf ──────────────────────────────────────────────────────────────────────

def _process_pdf(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"

    if action == "info":
        try:
            n = len(_pdf_pages(path))
            return f"PDF: {n} pages, size: {_file_size_str(path)}"
        except Exception:
            return f"PDF size: {_file_size_str(path)}"

    if action == "extract_pages":
        if not params.get("pages"):
            return _need("Which pages should I extract? (e.g. 1-3 or 2,5)")
        text = _read_pdf(path, params)
        out = _output_path(path, "pages", ".txt")
        _save_text(out, text)
        return _done(out, f"Extracted pages {params['pages']}.")

    if action == "to_word":
        text = _read_pdf(path, {})
        try:
            from docx import Document
        except ImportError:
            return "python-docx not installed. Run: pip install python-docx"
        doc = Document()
        doc.add_heading(path.stem, 0)
        for para in re.split(r"\n\s*\n", text):
            if para.strip():
                doc.add_paragraph(para.strip())
        out = _output_path(path, "converted", ".docx")
        doc.save(out)
        return _done(out, "Converted to Word document.")

    return _universal(path, "pdf", action, params)


# ── data ─────────────────────────────────────────────────────────────────────

def _process_data(path: Path, ftype: str, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    if action in ("read",):
        return _read_any(path, ftype, params)
    try:
        import pandas as pd
        tables = _load_tables(path, ftype)
    except Exception as e:
        return f"FAILED: could not read file: {e}"

    sheet = params.get("sheet")
    name = sheet if sheet in tables else next(iter(tables))
    df = tables[name]

    if action == "info":
        return (f"Sheets: {', '.join(map(str, tables))}\nRows: {len(df)}, Columns: {len(df.columns)}\n"
                f"Columns: {', '.join(map(str, df.columns))}\nSize: {_file_size_str(path)}")

    if action == "stats":
        try:
            return f"Statistics ({name}):\n{df.describe(include='all').to_string()[:3000]}"
        except Exception as e:
            return f"Stats failed: {e}"

    if action == "analyze":
        prompt = (f"Analyze this dataset. Columns: {list(df.columns)}\nRows: {len(df)}\n"
                  f"Preview:\n{df.head(50).to_string()}\n\nGive insights, patterns and notable findings.")
        try:
            return _ask(prompt)
        except Exception as e:
            return f"FAILED: AI analysis failed: {e}"

    if action in ("convert", "to_csv", "to_excel", "to_json"):
        fmt = {"to_csv": "csv", "to_excel": "xlsx", "to_json": "json"}.get(
            action, str(params.get("format") or "").lower().strip("."))
        if not fmt:
            return _need("Which format should I convert it to? (csv, xlsx, json)")
        try:
            out = _output_path(path, "converted", f".{fmt}")
            if fmt == "csv":
                df.to_csv(out, index=False, encoding="utf-8-sig")
            elif fmt in ("xlsx", "xls"):
                with pd.ExcelWriter(out) as w:
                    for n, d in tables.items():
                        d.to_excel(w, sheet_name=str(n)[:31], index=False)
            elif fmt == "json":
                df.to_json(out, orient="records", force_ascii=False, indent=2)
            else:
                return f"Unsupported target format: {fmt}"
            return _done(out, f"Converted to {fmt.upper()}.")
        except Exception as e:
            return f"FAILED: convert failed: {e}"

    if action == "filter":
        col, value = params.get("column", ""), params.get("value", "")
        cond = str(params.get("condition") or "equals").lower()
        if not col or col not in df.columns:
            return _need(f"Which column should I filter? Available: {', '.join(map(str, df.columns))}")
        try:
            s = df[col]
            sl = s.astype(str).str.lower()
            v = str(value).lower()
            if cond in ("equals", "eq"):
                mask = sl == v
                try:
                    mask = mask | (pd.to_numeric(s, errors="coerce") == float(value))
                except ValueError:
                    pass
            elif cond in ("not_equals", "ne"):
                mask = sl != v
            elif cond == "contains":
                mask = sl.str.contains(re.escape(v), na=False)
            elif cond == "starts_with":
                mask = sl.str.startswith(v, na=False)
            elif cond in ("gt", "lt", "gte", "lte"):
                num = pd.to_numeric(s, errors="coerce")
                f = float(value)
                mask = {"gt": num > f, "lt": num < f, "gte": num >= f, "lte": num <= f}[cond]
            else:
                mask = sl == v
            filtered = df[mask]
            out = _output_path(path, "filtered", ".csv")
            filtered.to_csv(out, index=False, encoding="utf-8-sig")
            return _done(out, f"{len(filtered)} rows match.")
        except Exception as e:
            return f"FAILED: filter failed: {e}"

    if action == "sort":
        col = params.get("column") or str(df.columns[0])
        if col not in df.columns:
            return _need(f"Which column should I sort by? Available: {', '.join(map(str, df.columns))}")
        try:
            asc = _flag(params, "ascending", True)
            out = _output_path(path, "sorted", ".csv")
            df.sort_values(col, ascending=asc).to_csv(out, index=False, encoding="utf-8-sig")
            return _done(out, f"Sorted by '{col}'.")
        except Exception as e:
            return f"FAILED: sort failed: {e}"

    # any other request → give the AI the data plus the instruction
    task = (params.get("instruction") or action)
    try:
        return _ask(f"Task: {task}\nDataset ({len(df)} rows, cols: {list(df.columns)}):\n{df.head(60).to_string()}")
    except Exception as e:
        return f"FAILED: processing failed: {e}"


# ── json / xml ───────────────────────────────────────────────────────────────

def _process_json(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    if action == "read":
        return _read_any(path, "json", params)
    try:
        data = json.loads(_read_text_file(path))
    except Exception as e:
        return f"Invalid JSON: {e}"

    if action == "validate":
        return f"Valid JSON. Type: {type(data).__name__}, size: {_file_size_str(path)}"
    if action == "format":
        out = _output_path(path, "formatted", ".json")
        _save_text(out, json.dumps(data, indent=2, ensure_ascii=False))
        return _done(out, "Formatted JSON.")
    if action == "to_csv":
        try:
            import pandas as pd
            if not isinstance(data, (list, dict)):
                return "JSON must be an object or array to convert to CSV."
            df = pd.json_normalize(data)
            out = _output_path(path, "converted", ".csv")
            df.to_csv(out, index=False, encoding="utf-8-sig")
            return _done(out, "Converted to CSV.")
        except ImportError:
            return "pandas not installed. Run: pip install pandas"
        except Exception as e:
            return f"FAILED: convert failed: {e}"
    return _universal(path, "json", action if action not in ("analyze", "summarize") else action, params)


def _process_xml(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    if action == "read":
        return _read_any(path, "xml", params)
    if action == "validate":
        try:
            ET.parse(path)
            return f"Valid XML. Size: {_file_size_str(path)}"
        except Exception as e:
            return f"Invalid XML: {e}"
    if action == "format":
        try:
            tree = ET.parse(path)
            ET.indent(tree)
            out = _output_path(path, "formatted")
            tree.write(out, encoding="utf-8", xml_declaration=True)
            return _done(out, "Formatted XML.")
        except Exception as e:
            return f"FAILED: format failed: {e}"
    return _universal(path, "xml", action, params)


# ── code ─────────────────────────────────────────────────────────────────────

def _process_code(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    ext = path.suffix.lstrip(".").lower()

    if action == "read":
        return _read_any(path, "code", params)
    if action == "info":
        text = _read_text_file(path)
        return f"Code file: {text.count(chr(10)) + 1} lines, {len(text.split())} words, {_file_size_str(path)}"

    if action == "run":
        runners = {"py": [sys.executable], "js": ["node"]}
        if ext not in runners:
            return f"Direct execution is not supported for .{ext} files."
        if ext == "js" and not shutil.which("node"):
            return "Node.js is not installed."
        try:
            r = subprocess.run(runners[ext] + [str(path)], capture_output=True, text=True, timeout=30,
                               cwd=str(path.parent), errors="replace")
            out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
            return f"Exit code {r.returncode}.\n{out[:3000]}" if out.strip() else f"Exit code {r.returncode}. No output."
        except subprocess.TimeoutExpired:
            return "Execution timed out (30s)."
        except Exception as e:
            return f"FAILED: run failed: {e}"

    return _universal(path, "code", action, params)


# ── text / docx / pptx / odf / rtf / epub / unknown-text ────────────────────

def _process_doc(path: Path, ftype: str, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    if action == "read":
        return _read_any(path, ftype, params)
    if action == "to_pdf" and ftype in ("docx", "pptx", "odf", "rtf"):
        try:
            out_dir = Path(tempfile.mkdtemp(prefix="jarvis_pdf_"))
            tmp = _soffice_convert(path, "pdf", out_dir)
            out = _output_path(path, "converted", ".pdf")
            shutil.move(str(tmp), str(out))
            return _done(out, "Converted to PDF.")
        except Exception as e:
            return f"FAILED: PDF conversion failed: {e}"
    return _universal(path, ftype, action, params)


# ── audio ────────────────────────────────────────────────────────────────────

_AUDIO_MIME = {"mp3": "audio/mp3", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4",
               "aac": "audio/aac", "flac": "audio/flac", "opus": "audio/ogg"}


def _ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _run(cmd, timeout):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.returncode == 0, (r.stderr or "")[-300:]
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def _transcribe(audio_path: Path, ref: Path, params: dict, save: bool = True) -> str:
    data_path = audio_path
    tmp = None
    if audio_path.stat().st_size > 19 * 1024 * 1024:
        if not _ffmpeg():
            raise RuntimeError("Audio is over 19 MB and ffmpeg is not installed to shrink it.")
        fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        tmp = Path(tmp_name)
        ok, err = _run(["ffmpeg", "-i", str(audio_path), "-vn", "-ac", "1", "-b:a", "48k", str(tmp), "-y"], 900)
        if not ok:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Could not shrink audio: {err}")
        data_path = tmp
    try:
        mime = _AUDIO_MIME.get(data_path.suffix.lstrip(".").lower(), "audio/mpeg")
        result = _ask(["Transcribe all speech in this audio accurately.",
                       {"mime_type": mime, "data": data_path.read_bytes()}])
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    if save and _flag(params, "save", True):
        out = _output_path(ref, "transcript", ".txt")
        if _save_text(out, result):
            return f"{result[:300]}...\n\nVERIFIED: full transcript saved: {out.resolve()}" if len(result) > 300 \
                else f"{result}\n\nVERIFIED: transcript saved: {out.resolve()}"
    return result


def _process_audio(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"

    if action == "info":
        try:
            from pydub import AudioSegment
            a = AudioSegment.from_file(path)
            m, s = divmod(int(len(a) / 1000), 60)
            return f"Audio: {m}m {s}s, {a.channels} ch, {a.frame_rate}Hz, {_file_size_str(path)}"
        except ImportError:
            return f"Audio file: {_file_size_str(path)} (install pydub for more info)"
        except Exception as e:
            return f"Info failed: {e}"

    if action in ("read", "transcribe"):
        try:
            return _transcribe(path, path, params, save=(action == "transcribe"))
        except Exception as e:
            return f"FAILED: transcription failed: {e}"

    if action == "convert":
        fmt = str(params.get("format") or "").lstrip(".")
        if not fmt:
            return _need("Which format should I convert the audio to? (mp3, wav, ogg, flac)")
        try:
            from pydub import AudioSegment
            out = _output_path(path, "converted", f".{fmt}")
            AudioSegment.from_file(path).export(out, format=fmt)
            return _done(out, f"Converted to {fmt.upper()}.")
        except ImportError:
            return "pydub not installed. Run: pip install pydub"
        except Exception as e:
            return f"FAILED: convert failed: {e}"

    if action == "trim":
        if params.get("start") in (None, "") and params.get("end") in (None, ""):
            return _need("From which time to which time should I trim? (seconds or HH:MM:SS)")
        try:
            from pydub import AudioSegment
            start, end = _to_seconds(params.get("start")), _to_seconds(params.get("end"))
            audio = AudioSegment.from_file(path)
            seg = audio[int(start * 1000): int(end * 1000) if end else len(audio)]
            out = _output_path(path, f"trim_{int(start)}s_{int(end)}s")
            seg.export(out, format=path.suffix.lstrip("."))
            return _done(out, f"Trimmed audio ({int(start)}s–{int(end) if end else 'end'}).")
        except ImportError:
            return "pydub not installed. Run: pip install pydub"
        except Exception as e:
            return f"FAILED: trim failed: {e}"

    return f"Unknown audio action: '{action}'. Try: read, transcribe, info, convert, trim"


# ── video ────────────────────────────────────────────────────────────────────

def _video_info(path: Path) -> str:
    if not shutil.which("ffprobe"):
        return f"Video file: {_file_size_str(path)} (ffprobe not found for details)"
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format",
                            "-show_streams", str(path)], capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        dur = float(data.get("format", {}).get("duration", 0))
        m, s = divmod(int(dur), 60)
        v = next((x for x in data.get("streams", []) if x.get("codec_type") == "video"), {})
        fps = v.get("r_frame_rate", "0/1")
        try:
            a, b = fps.split("/")
            fps = f"{float(a) / float(b):.1f}"
        except Exception:
            pass
        return f"Video: {m}m {s}s, {v.get('width', '?')}x{v.get('height', '?')}, {fps} fps, {_file_size_str(path)}"
    except Exception:
        return f"Video file: {_file_size_str(path)}"


def _video_transcript(path: Path, params: dict, save: bool = False) -> str:
    if not _ffmpeg():
        raise RuntimeError("ffmpeg not found (needed for video transcription).")
    fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        ok, err = _run(["ffmpeg", "-i", str(path), "-vn", "-ac", "1", "-b:a", "48k", str(tmp), "-y"], 900)
        if not ok or tmp.stat().st_size == 0:
            raise RuntimeError(f"no audio track could be extracted ({err})")
        return _transcribe(tmp, path, params, save=save)
    finally:
        tmp.unlink(missing_ok=True)


def _process_video(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"

    if action == "info":
        return _video_info(path)
    if action == "read":
        return _read_any(path, "video", params)

    if not _ffmpeg():
        return "ffmpeg not found. Install ffmpeg to process video."

    if action == "transcribe":
        try:
            return _video_transcript(path, params, save=True)
        except Exception as e:
            return f"FAILED: video transcription failed: {e}"

    if action == "extract_audio":
        out = _output_path(path, "audio", ".mp3")
        ok, err = _run(["ffmpeg", "-i", str(path), "-q:a", "0", "-map", "a", str(out), "-y"], 600)
        return _done(out, "Audio extracted.") if ok else f"FAILED: extract audio failed: {err}"

    if action == "trim":
        if params.get("start") in (None, "") and params.get("end") in (None, ""):
            return _need("From which time to which time should I trim the video? (seconds or HH:MM:SS)")
        out = _output_path(path, "trim")
        cmd = ["ffmpeg", "-i", str(path), "-ss", str(params.get("start") or "0")]
        if params.get("end"):
            cmd += ["-to", str(params["end"])]
        cmd += ["-c", "copy", str(out), "-y"]
        ok, err = _run(cmd, 900)
        return _done(out, "Trimmed video.") if ok else f"FAILED: trim failed: {err}"

    if action == "extract_frame":
        ts = str(params.get("timestamp") or "00:00:01")
        out = _output_path(path, f"frame_{ts.replace(':', '')}", ".jpg")
        ok, err = _run(["ffmpeg", "-i", str(path), "-ss", ts, "-vframes", "1", str(out), "-y"], 60)
        return _done(out, f"Frame extracted at {ts}.") if ok else f"FAILED: extract frame failed: {err}"

    if action == "compress":
        q = params.get("quality")
        crf = 28 if q in (None, "") else min(max(round(51 - 0.33 * int(q)), 18), 35)   # quality 1-100 → crf
        out = _output_path(path, f"compressed_crf{crf}", ".mp4")
        ok, err = _run(["ffmpeg", "-i", str(path), "-c:v", "libx264", "-crf", str(crf),
                        "-preset", "medium", "-c:a", "aac", str(out), "-y"], 3600)
        if ok:
            return _done(out, f"Compressed: {_file_size_str(path)} → {_file_size_str(out)}.")
        return f"FAILED: compress failed: {err}"

    if action == "convert":
        fmt = str(params.get("format") or "").lstrip(".")
        if not fmt:
            return _need("Which format should I convert the video to? (mp4, mkv, webm, avi)")
        out = _output_path(path, "converted", f".{fmt}")
        ok, err = _run(["ffmpeg", "-i", str(path), str(out), "-y"], 3600)
        return _done(out, f"Converted to {fmt.upper()}.") if ok else f"FAILED: convert failed: {err}"

    return (f"Unknown video action: '{action}'. Try: read, info, trim, extract_audio, extract_frame, "
            f"compress, transcribe, convert")


# ── archive ──────────────────────────────────────────────────────────────────

def _safe_extract(path: Path, dest: Path):
    dest_res = dest.resolve()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if not (dest_res / n).resolve().is_relative_to(dest_res):
                    raise RuntimeError(f"Unsafe path in archive: {n}")
            z.extractall(dest)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as t:
            for m in t.getmembers():
                if not (dest_res / m.name).resolve().is_relative_to(dest_res):
                    raise RuntimeError(f"Unsafe path in archive: {m.name}")
            t.extractall(dest)
    elif path.suffix.lower() == ".7z":
        import py7zr
        with py7zr.SevenZipFile(path) as z:
            z.extractall(dest)
    elif path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as f, open(dest / path.stem, "wb") as o:
            shutil.copyfileobj(f, o)
    else:
        raise RuntimeError(f"Unsupported archive format: {path.suffix} (for .7z: pip install py7zr)")


def _process_archive(path: Path, action: str, params: dict, speak=None) -> str:
    action = action or "read"
    if action in ("read", "list"):
        try:
            return _read_any(path, "archive", params)
        except Exception as e:
            return f"FAILED: {e}"
    if action == "extract":
        dest_raw = params.get("destination")
        dest = Path(_try_resolve(str(dest_raw)) or dest_raw) if dest_raw else path.parent / path.stem
        try:
            dest.mkdir(parents=True, exist_ok=True)
            _safe_extract(path, dest)
            n = sum(1 for _ in dest.rglob("*"))
            return f"VERIFIED: extracted to {dest.resolve()} ({n} items)." if n else f"FAILED: nothing was extracted to {dest}."
        except Exception as e:
            return f"FAILED: extract failed: {e}"
    return f"Unknown archive action: '{action}'. Try: read, list, extract"


# ── sqlite / binary ──────────────────────────────────────────────────────────

def _process_sqlite(path: Path, action: str, params: dict, speak=None) -> str:
    try:
        if action in ("", "read", "info", "list"):
            return _read_any(path, "sqlite", params)
        if action == "query":
            if not params.get("query"):
                return _need("Which SELECT query should I run?")
            return _sqlite_summary(path, str(params["query"]))
    except Exception as e:
        return f"FAILED: database error: {e}"
    return _universal(path, "sqlite", action, params)


def _process_binary(path: Path, action: str, params: dict, speak=None) -> str:
    if action == "info":
        return _basic_info(path, "binary")
    return _binary_summary(path)


# ═════════════════════════════════════════════════════════════════════════════
#  main entry
# ═════════════════════════════════════════════════════════════════════════════

_ALIASES = {
    "read_file": "read", "open": "read", "view": "read", "show": "read", "cat": "read",
    "content": "read", "contents": "read", "read_content": "read", "get_content": "read",
    "text": "read", "summary": "summarize", "transcript": "transcribe", "list_files": "list",
}


def file_processor(parameters: dict = None, player=None, speak=None) -> str:
    global _LAST_FILE
    parameters = dict(parameters or {})

    try:
        path, note = _locate(parameters)
    except Exception as e:
        return f"FAILED: could not look for the file: {e}"
    if path is None:
        return note                                    # NEED_INFO …
    if not path.is_file():
        return f"FAILED: '{path}' is not a file."
    if _fc_safe is not None and not _fc_safe(path):
        return f"Access denied: {path}"

    _LAST_FILE = path
    ftype = _detect_type(path)
    if ftype == "unknown":
        ftype = "text" if _looks_text(path) else "binary"

    action = (parameters.get("action") or "").lower().strip().replace(" ", "_")
    action = _ALIASES.get(action, action)
    if ftype == "text" and action == "transcribe":
        action = "read"

    log_msg = f"[FileProcessor] {ftype.upper()} | {path} | action={action or 'read'}"
    print(log_msg)
    if player:
        try:
            player.write_log(log_msg)
        except Exception:
            pass

    dispatch = {
        "image":   lambda: _process_image(path, action, parameters, speak),
        "pdf":     lambda: _process_pdf(path, action, parameters, speak),
        "docx":    lambda: _process_doc(path, "docx", action, parameters, speak),
        "odf":     lambda: _process_doc(path, "odf", action, parameters, speak),
        "rtf":     lambda: _process_doc(path, "rtf", action, parameters, speak),
        "epub":    lambda: _process_doc(path, "epub", action, parameters, speak),
        "text":    lambda: _process_doc(path, "text", action, parameters, speak),
        "pptx":    lambda: _process_doc(path, "pptx", action, parameters, speak),
        "csv":     lambda: _process_data(path, "csv", action, parameters, speak),
        "excel":   lambda: _process_data(path, "excel", action, parameters, speak),
        "json":    lambda: _process_json(path, action, parameters, speak),
        "xml":     lambda: _process_xml(path, action, parameters, speak),
        "code":    lambda: _process_code(path, action, parameters, speak),
        "audio":   lambda: _process_audio(path, action, parameters, speak),
        "video":   lambda: _process_video(path, action, parameters, speak),
        "archive": lambda: _process_archive(path, action, parameters, speak),
        "sqlite":  lambda: _process_sqlite(path, action, parameters, speak),
        "binary":  lambda: _process_binary(path, action, parameters, speak),
    }
    handler = dispatch.get(ftype)
    if not handler:
        return f"Unsupported file type: {ftype}"

    try:
        result = handler() or "Done."
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"FAILED: processing error: {e}"
    return f"{note}\n{result}" if note else result


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "file_processor",
    "description": (
        "Reads and processes ANY file silently (it never opens an app window): images (OCR/describe/resize/compress/"
        "convert/crop/rotate), PDFs (read/summarize/extract_pages/to_word), Word/RTF/ODT/EPUB/text files "
        "(read/summarize/fix/reformat/translate/word_count/to_pdf), CSV/Excel (read/analyze/stats/filter/sort/convert), "
        "JSON/XML (read/validate/format/analyze), code (read/explain/review/fix/optimize/run/document/test), audio "
        "(read=transcribe/trim/convert/info), video (read/trim/extract_audio/extract_frame/compress/transcribe), "
        "archives (read=list/extract, member=read one file inside), presentations (read/summarize/to_pdf), SQLite "
        "databases (read/query). Use it whenever the user wants to READ, SUMMARIZE or CHANGE a file. "
        "FINDING THE FILE: pass whatever the user said. If they gave a full path use file_path. If they said a "
        "drive/folder (e.g. 'D drive, folder college') put it in folder; the file name (spoken is fine, e.g. 'lecture "
        "notes dot pdf') goes in name. Leave all empty to use the last/uploaded file. The tool searches Desktop, "
        "Downloads, Documents and ALL drives by itself. "
        "RULES: (1) If a result starts with NEED_INFO, ask the user that exact question and wait, then call again "
        "(use the full path the user picks). (2) Default action is 'read' — to read a file, do not open it with "
        "file_controller. (3) Only say something was saved/converted/created if the result contains VERIFIED. If it "
        "contains FAILED, tell the user it failed and why."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {"type": "STRING",
                          "description": "Full path, or whatever address the user said (e.g. 'D:/college/notes.pdf'). Optional if folder+name are given."},
            "folder": {"type": "STRING",
                       "description": "Folder/drive the user mentioned, in their own words: 'D drive college semester 3', 'downloads'."},
            "name": {"type": "STRING",
                     "description": "File name as the user said it, extension optional: 'lecture notes', 'report.pdf'."},
            "action": {"type": "STRING",
                       "description": "read (default) | summarize | analyze | extract_text | extract_pages | to_word | to_pdf | "
                                      "fix | reformat | translate | word_count | info | stats | filter | sort | convert | "
                                      "validate | format | explain | review | optimize | document | test | run | transcribe | "
                                      "trim | extract_audio | extract_frame | compress | resize | crop | rotate | list | "
                                      "extract | query"},
            "instruction": {"type": "STRING",
                            "description": "Free-form instruction if no action fits, e.g. 'find all email addresses'"},
            "language": {"type": "STRING", "description": "Target language for action=translate"},
            "max_chars": {"type": "INTEGER", "description": "How many characters to return when reading (default 8000)"},
            "offset": {"type": "INTEGER", "description": "Start position when reading a long file in parts"},
            "pages": {"type": "STRING", "description": "PDF pages, e.g. '1-3,5'"},
            "member": {"type": "STRING", "description": "File inside a zip/tar to read without extracting"},
            "sheet": {"type": "STRING", "description": "Sheet name for Excel actions"},
            "query": {"type": "STRING", "description": "SELECT query for SQLite files"},
            "format": {"type": "STRING", "description": "Target format for conversion, e.g. 'mp3', 'csv', 'png'"},
            "width": {"type": "INTEGER", "description": "Target width for image resize"},
            "height": {"type": "INTEGER", "description": "Target height for image resize"},
            "scale": {"type": "NUMBER", "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality": {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "left": {"type": "INTEGER", "description": "Crop box left (px)"},
            "top": {"type": "INTEGER", "description": "Crop box top (px)"},
            "right": {"type": "INTEGER", "description": "Crop box right (px)"},
            "bottom": {"type": "INTEGER", "description": "Crop box bottom (px)"},
            "angle": {"type": "NUMBER", "description": "Rotation angle in degrees"},
            "start": {"type": "STRING", "description": "Start time for trim: seconds or HH:MM:SS"},
            "end": {"type": "STRING", "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING", "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column": {"type": "STRING", "description": "Column name for filter/sort"},
            "value": {"type": "STRING", "description": "Filter value"},
            "condition": {"type": "STRING",
                          "description": "equals|not_equals|contains|starts_with|gt|lt|gte|lte"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order (default: true)"},
            "save": {"type": "BOOLEAN", "description": "Save long AI results to a file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": [],
    },
    "handler": file_processor,
}