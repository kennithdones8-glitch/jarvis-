"""Document reading: PDF, Word (.docx), and plain-text formats, inside approved folders.

Read-only (Tier 0). Text is returned marked untrusted — a document is data, never instructions.
Limits guard against huge or hostile files (size caps, a decompression cap for .docx).
Not supported yet: scanned/image-only PDFs (no OCR), .doc (old Word), .pages, spreadsheets.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ..core.permissions import ResourceKind, Tier
from ..core.tools import ActionSpec, CallContext, ToolError, ToolSpec
from .web import html_to_text

MAX_FILE_BYTES = 50_000_000
MAX_XML_BYTES = 50_000_000
MAX_CHARS = 200_000
MAX_PAGES = 300
TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".rst", ".yaml", ".yml", ".xml"}
HTML_TYPES = {".html", ".htm"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def parse_pages(spec: Any, total: int) -> list[int]:
    """'3', '2-5', '1,4-6' → zero-based page indexes within the document."""
    if spec in (None, ""):
        return list(range(min(total, MAX_PAGES)))
    if isinstance(spec, int):
        spec = str(spec)
    if not isinstance(spec, str) or not re.fullmatch(r"\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*", spec):
        raise ToolError("pages must look like '3', '2-5' or '1,4-6'")
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        lo, hi = int(a), int(b or a)
        if lo < 1 or hi < lo:
            raise ToolError(f"invalid page range {part.strip()}")
        out.extend(range(lo - 1, min(hi, total)))
    if not out:
        raise ToolError(f"the document has only {total} pages")
    return sorted(set(out))[:MAX_PAGES]


def _clip(text: str) -> tuple[str, bool]:
    return (text[:MAX_CHARS], len(text) > MAX_CHARS)


def read_pdf(path: Path, pages: Any = None) -> dict[str, Any]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ToolError("this PDF is password-protected")
        total = len(reader.pages)
        wanted = parse_pages(pages, total)
        parts, empty = [], 0
        for i in wanted:
            text = (reader.pages[i].extract_text() or "").strip()
            empty += not text
            parts.append(f"--- Page {i + 1} ---\n{text}")
        title = (reader.metadata.title if reader.metadata else None) or None
    except ToolError:
        raise
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        raise ToolError(f"could not read this PDF: {exc}") from None
    content, truncated = _clip("\n\n".join(parts))
    note = None
    if wanted and empty == len(wanted):
        note = "No text found: this PDF looks scanned (images only). Reading scanned PDFs (OCR) isn't supported yet."
    elif empty:
        note = f"{empty} of {len(wanted)} pages had no extractable text (possibly images)."
    return {"format": "pdf", "pages_total": total, "pages_read": [i + 1 for i in wanted], "title": title,
            "content": content, "truncated": truncated or len(wanted) < total, "note": note}


def read_docx(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise ToolError("this Word file is too large to read safely")
            root = ElementTree.fromstring(z.read(info))
    except ToolError:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, OSError):
        raise ToolError("not a readable .docx file (old .doc files aren't supported — save as .docx)") from None
    body = root.find(f"{W}body")
    lines: list[str] = []
    for el in (body if body is not None else []):
        if el.tag == f"{W}p":
            text = "".join(t.text or "" for t in el.iter(f"{W}t"))
            style = el.find(f"{W}pPr/{W}pStyle")
            heading = style is not None and (style.get(f"{W}val") or "").lower().startswith("heading")
            if text.strip():
                lines.append(f"## {text.strip()}" if heading else text)
        elif el.tag == f"{W}tbl":
            for row in el.iter(f"{W}tr"):
                cells = ["".join(t.text or "" for t in cell.iter(f"{W}t")).strip() for cell in row.iter(f"{W}tc")]
                lines.append("| " + " | ".join(cells) + " |")
    content, truncated = _clip("\n".join(lines))
    return {"format": "docx", "paragraphs": len(lines), "content": content, "truncated": truncated,
            "note": None if lines else "The document has no text."}


def read_text(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ToolError("this looks like a binary file, not text")
    text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() in HTML_TYPES:
        title, text = html_to_text(text)
        content, truncated = _clip(text)
        return {"format": "html", "title": title or None, "content": content, "truncated": truncated, "note": None}
    content, truncated = _clip(text)
    return {"format": path.suffix.lower().lstrip(".") or "text", "content": content, "truncated": truncated, "note": None}


class DocumentTool:
    def spec(self) -> ToolSpec:
        path = ResourceKind.PATH
        return ToolSpec("doc", "Read PDF, Word and text documents inside approved folders", {
            "read": ActionSpec(Tier.READ, "path", path, timeout_s=90),
            "info": ActionSpec(Tier.READ, "path", path, timeout_s=30),
        }, self.handle)

    def handle(self, action: str, args: dict[str, Any], ctx: CallContext) -> Any:
        path = Path(ctx.resource)
        if not path.is_file():
            raise ToolError(f"not a file: {path}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ToolError("file is larger than 50 MB")
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            result = read_pdf(path, args.get("pages"))
        elif suffix == ".docx":
            result = read_docx(path)
        elif suffix in TEXT_TYPES | HTML_TYPES or suffix == "":
            result = read_text(path)
        else:
            raise ToolError(f"can't read {suffix} files yet (supported: PDF, .docx, text, Markdown, CSV, HTML)")
        result.update(path=str(path), name=path.name, bytes=size, untrusted=True)
        if action == "info":
            text = result.pop("content")
            result.update(words=len(text.split()), preview=text[:500])
        else:
            result["words"] = len(result["content"].split())
        return result
