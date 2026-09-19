"""Safe file storage and document text extraction."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from ..config import settings

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "text/markdown",
    "application/octet-stream",  # browsers sometimes send this for .docx
)


class UploadRejected(Exception):
    """Raised when an upload fails validation."""


def safe_filename(name: str) -> str:
    """Strip any path component and unsafe characters — never trust the client."""
    name = unicodedata.normalize("NFKD", name or "file")
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ \-()]+", "_", name).strip(" .")
    return (name or "file")[:120]


def validate_upload(filename: str, content_type: str | None, size: int) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"Unsupported file type '{ext}'. Allowed: PDF, DOCX, TXT.")
    if content_type and not any(content_type.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise UploadRejected("Unsupported content type.")
    if size > settings.max_upload_bytes:
        raise UploadRejected(f"File exceeds the {settings.max_upload_mb} MB limit.")
    return ext


def case_dir(user_id: str, case_id: str, bucket: str) -> Path:
    """backend/data/uploads/{user_id}/{case_id}/{bucket}/ — created on demand."""
    base = (settings.uploads_dir / user_id / case_id / bucket).resolve()
    root = settings.uploads_dir.resolve()
    if not str(base).startswith(str(root)):  # defence in depth against traversal
        raise UploadRejected("Invalid storage path.")
    base.mkdir(parents=True, exist_ok=True)
    return base


def store_bytes(directory: Path, filename: str, data: bytes) -> Path:
    target = directory / safe_filename(filename)
    stem, suffix, i = target.stem, target.suffix, 1
    while target.exists():
        target = directory / f"{stem}_{i}{suffix}"
        i += 1
    target.write_bytes(data)
    return target


# ── text extraction ───────────────────────────────────────────────────────────

def _paragraphs(block: str) -> list[dict]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", block) if p.strip()]
    if not parts:
        parts = [line.strip() for line in block.splitlines() if line.strip()]
    return [{"n": i + 1, "text": re.sub(r"[ \t]+", " ", p)} for i, p in enumerate(parts)]


def extract_pdf(path: Path) -> list[dict]:
    import pymupdf  # PyMuPDF

    pages: list[dict] = []
    with pymupdf.open(path) as doc:
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append({"page": index, "paragraphs": _paragraphs(text)})
    return pages


def extract_docx(path: Path) -> list[dict]:
    from docx import Document as Docx

    doc = Docx(str(path))
    blocks = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    # DOCX has no reliable page boundaries; chunk ~30 paragraphs per logical page.
    pages: list[dict] = []
    chunk = 30
    for i in range(0, max(len(blocks), 1), chunk):
        part = blocks[i : i + chunk]
        pages.append(
            {"page": len(pages) + 1, "paragraphs": [{"n": j + 1, "text": t} for j, t in enumerate(part)]}
        )
    return pages


def extract_txt(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = _paragraphs(text)
    pages: list[dict] = []
    chunk = 40
    for i in range(0, max(len(blocks), 1), chunk):
        part = blocks[i : i + chunk]
        pages.append(
            {"page": len(pages) + 1, "paragraphs": [{"n": j + 1, "text": p["text"]} for j, p in enumerate(part)]}
        )
    return pages


def extract_pages(path: Path) -> list[dict]:
    """Return [{page, paragraphs:[{n, text}]}] for a stored document."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            pages = extract_pdf(path)
        elif suffix == ".docx":
            pages = extract_docx(path)
        else:
            pages = extract_txt(path)
    except Exception as exc:  # pragma: no cover - corrupt file handling
        raise UploadRejected(f"Could not read the document text ({type(exc).__name__}).") from exc
    return [p for p in pages if p["paragraphs"]] or [{"page": 1, "paragraphs": []}]


def pages_to_text(pages: list[dict]) -> str:
    out: list[str] = []
    for page in pages:
        out.append(f"[PAGE {page['page']}]")
        for para in page["paragraphs"]:
            out.append(f"({page['page']}.{para['n']}) {para['text']}")
    return "\n".join(out)


def text_from_pages(pages: list[dict]) -> str:
    return "\n\n".join(p["text"] for page in pages for p in page["paragraphs"])
