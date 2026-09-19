"""Case, document, transcript and audit services.

All case-scoped reads go through `get_owned_case`, which is the single point
where ownership is enforced. The REST routes and the MCP tools both call these
services — the MCP layer never reaches the database directly.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AuditEvent, Case, Citation, Claim, ClaimEvidence, Document, Evidence,
    Finding, Report, Review, Transcript, User, uid, utcnow,
)
from ..utils import files as fileutil
from ..utils.ids import next_index, seq_id
from ..utils.serialize import dumps


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


# ── audit ─────────────────────────────────────────────────────────────────────

def log_event(
    db: Session,
    case_row_id: str,
    *,
    action: str,
    object_type: str = "case",
    object_id: str = "",
    actor: str = "System",
    actor_type: str = "system",
    previous_state: str | None = None,
    new_state: str | None = None,
    details: str | None = None,
    commit: bool = True,
) -> AuditEvent:
    count = db.scalar(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case_row_id)
    ) or 0
    event = AuditEvent(
        log_id=f"AL-{str(count + 1).zfill(4)}",
        case_id=case_row_id,
        actor=actor,
        actor_type=actor_type,
        action=action,
        object_type=object_type,
        object_id=object_id,
        previous_state=previous_state,
        new_state=new_state,
        details=details,
    )
    db.add(event)
    if commit:
        db.commit()
    return event


def list_audit(db: Session, case_row_id: str) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent).where(AuditEvent.case_id == case_row_id).order_by(AuditEvent.created_at)
        )
    )


# ── cases ─────────────────────────────────────────────────────────────────────

def next_case_public_id(db: Session) -> str:
    year = datetime.now().year
    prefix = f"NS-{year}-"
    existing = list(db.scalars(select(Case.case_id).where(Case.case_id.like(f"{prefix}%"))))
    numbers = [int(v.rsplit("-", 1)[1]) for v in existing if v.rsplit("-", 1)[1].isdigit()]
    return f"{prefix}{str(max(numbers, default=0) + 1).zfill(3)}"


def create_case(db: Session, user: User, payload: dict) -> Case:
    case = Case(
        case_id=next_case_public_id(db),
        user_id=user.id,
        name=payload["name"].strip(),
        case_number=(payload.get("caseNumber") or "").strip() or None,
        case_type=(payload.get("caseType") or "").strip() or None,
        jurisdiction=(payload.get("jurisdiction") or "").strip() or None,
        court=(payload.get("court") or "").strip() or None,
        description=(payload.get("description") or "").strip() or None,
        filed_on=(payload.get("filedOn") or "").strip() or None,
        status="DRAFT",
    )
    db.add(case)
    db.flush()
    log_event(
        db, case.id, action="Case created", object_type="case", object_id=case.case_id,
        actor=user.full_name, actor_type="reviewer", new_state="DRAFT",
        details=f"Case '{case.name}' created.", commit=False,
    )
    db.commit()
    db.refresh(case)
    return case


def list_cases(db: Session, user: User) -> list[Case]:
    return list(
        db.scalars(select(Case).where(Case.user_id == user.id).order_by(Case.updated_at.desc()))
    )


def get_owned_case(db: Session, user_id: str, case_public_id: str) -> Case:
    """The single ownership gate. Every case-scoped read and write goes through it."""
    case = db.scalar(select(Case).where(Case.case_id == case_public_id))
    if case is None:
        raise NotFound(f"No case was found for the supplied case_id '{case_public_id}'.")
    if case.user_id != user_id:
        # Same message as NotFound so ownership cannot be probed.
        raise NotFound(f"No case was found for the supplied case_id '{case_public_id}'.")
    return case


def case_counts(db: Session, case_row_id: str) -> dict:
    def count(model, *conditions):
        return db.scalar(
            select(func.count()).select_from(model).where(model.case_id == case_row_id, *conditions)
        ) or 0

    return {
        "documents": count(Document, Document.is_transcript == False),  # noqa: E712
        "transcripts": count(Transcript),
        "claims": count(Claim),
        "evidence": count(Evidence),
        "relationships": count(ClaimEvidence),
        "conflicts": count(Finding, Finding.kind == "conflict"),
        "findings": count(Finding),
        "citations": count(Citation),
        "reviews": count(Review),
        "reports": count(Report),
        "openFindings": count(Finding, Finding.status == "open"),
    }


def update_case(db: Session, case: Case, payload: dict, user: User) -> Case:
    mapping = {
        "name": "name", "caseNumber": "case_number", "caseType": "case_type",
        "jurisdiction": "jurisdiction", "court": "court", "description": "description",
        "status": "status", "filedOn": "filed_on",
    }
    changed = []
    for key, attr in mapping.items():
        if key in payload and payload[key] is not None:
            value = payload[key].strip() if isinstance(payload[key], str) else payload[key]
            if getattr(case, attr) != value:
                setattr(case, attr, value or None)
                changed.append(key)
    if changed:
        log_event(
            db, case.id, action="Case details updated", object_type="case", object_id=case.case_id,
            actor=user.full_name, actor_type="reviewer",
            details=f"Updated: {', '.join(changed)}", commit=False,
        )
    db.commit()
    db.refresh(case)
    return case


def delete_case(db: Session, case: Case) -> None:
    db.delete(case)
    db.commit()


def set_status(db: Session, case: Case, status: str, actor: str = "System") -> None:
    previous = case.status
    if previous == status:
        return
    case.status = status
    log_event(
        db, case.id, action="Case status changed", object_type="case", object_id=case.case_id,
        actor=actor, actor_type="system", previous_state=previous, new_state=status, commit=False,
    )
    db.commit()


# ── documents ─────────────────────────────────────────────────────────────────

CATEGORY_FOR_TYPE = {
    "FIR / Complaint": "Submissions",
    "Charge Sheet": "Submissions",
    "Witness Statement": "Statements",
    "Affidavit": "Statements",
    "Investigation Report": "Reports",
    "Medical Report": "Reports",
    "Forensic Report": "Reports",
    "CCTV Report": "Evidence",
    "Phone / Digital Record": "Evidence",
    "Court Filing": "Submissions",
    "Written Submission": "Submissions",
    "Evidence Report": "Evidence",
    "Hearing Transcript": "Hearings",
    "Other": "Reports",
}
DOCUMENT_TYPES = list(CATEGORY_FOR_TYPE.keys())


def next_document_id(db: Session, case_row_id: str) -> str:
    existing = list(db.scalars(select(Document.document_id).where(Document.case_id == case_row_id)))
    return seq_id("DOC", next_index(existing, "DOC"), 3)


def store_document(
    db: Session,
    case: Case,
    user: User,
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    document_type: str = "Other",
    is_transcript: bool = False,
) -> Document:
    fileutil.validate_upload(filename, content_type, len(data))
    bucket = "transcripts" if is_transcript else "documents"
    directory = fileutil.case_dir(user.id, case.case_id, bucket)
    path = fileutil.store_bytes(directory, filename, data)

    document = Document(
        document_id=next_document_id(db, case.id),
        case_id=case.id,
        filename=path.name,
        document_type=document_type if document_type in CATEGORY_FOR_TYPE else "Other",
        category=CATEGORY_FOR_TYPE.get(document_type, "Reports"),
        storage_path=str(path),
        mime_type=content_type,
        size_bytes=len(data),
        status="processing",
        is_transcript=is_transcript,
    )
    db.add(document)
    db.flush()
    process_document(db, document)
    log_event(
        db, case.id,
        action="Transcript uploaded" if is_transcript else "Document uploaded",
        object_type="document", object_id=document.document_id,
        actor=user.full_name, actor_type="reviewer",
        details=f"{document.filename} ({document.page_count} page(s)) indexed.", commit=False,
    )
    db.commit()
    db.refresh(document)
    return document


def process_document(db: Session, document: Document) -> None:
    """Extract pages, paragraphs and entities. Original file is always retained."""
    from ai_engine.extraction import extract_entities

    try:
        pages = fileutil.extract_pages(Path(document.storage_path))
        document.pages_json = dumps(pages)
        document.page_count = len(pages)
        document.extracted_text = fileutil.pages_to_text(pages)
        document.entities_json = dumps(extract_entities(pages))
        document.status = "indexed" if any(p["paragraphs"] for p in pages) else "needs_review"
    except Exception as exc:  # noqa: BLE001
        document.status = "error"
        document.pages_json = dumps([])
        document.extracted_text = ""
        document.entities_json = dumps([])
        document.page_count = 0
        _ = exc


def list_documents(db: Session, case_row_id: str) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(Document.case_id == case_row_id).order_by(Document.uploaded_at)
        )
    )


def get_document(db: Session, case_row_id: str, document_public_id: str) -> Document:
    doc = db.scalar(
        select(Document).where(
            Document.case_id == case_row_id, Document.document_id == document_public_id
        )
    )
    if doc is None:
        raise NotFound(f"No document was found for '{document_public_id}'.")
    return doc


def delete_document(db: Session, document: Document, user: User) -> None:
    try:
        Path(document.storage_path).unlink(missing_ok=True)
    except OSError:
        pass
    log_event(
        db, document.case_id, action="Document removed", object_type="document",
        object_id=document.document_id, actor=user.full_name, actor_type="reviewer", commit=False,
    )
    db.delete(document)
    db.commit()


# ── transcripts ───────────────────────────────────────────────────────────────

def create_transcript(
    db: Session,
    case: Case,
    user: User,
    *,
    hearing_date: str | None,
    hearing_number: str | None,
    court: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    data: bytes | None = None,
    pasted_text: str | None = None,
) -> Transcript:
    if not data and not (pasted_text and pasted_text.strip()):
        raise ValueError("Provide either a transcript file or pasted transcript text.")

    if not data:
        filename = filename or f"hearing-{(hearing_number or '1')}.txt"
        data = (pasted_text or "").encode("utf-8")
        content_type = "text/plain"

    document = store_document(
        db, case, user,
        filename=filename or "transcript.txt",
        content_type=content_type,
        data=data,
        document_type="Hearing Transcript",
        is_transcript=True,
    )

    existing = list(db.scalars(select(Transcript.transcript_id).where(Transcript.case_id == case.id)))
    transcript = Transcript(
        transcript_id=seq_id("HR", next_index(existing, "HR")),
        case_id=case.id,
        document_id=document.document_id,
        filename=document.filename,
        storage_path=document.storage_path,
        mime_type=document.mime_type,
        hearing_date=hearing_date or None,
        hearing_number=hearing_number or None,
        court=court or case.court,
        extracted_text=document.extracted_text,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    return transcript


def list_transcripts(db: Session, case_row_id: str) -> list[Transcript]:
    return list(
        db.scalars(
            select(Transcript).where(Transcript.case_id == case_row_id).order_by(Transcript.uploaded_at)
        )
    )


def document_pages(document: Document) -> list[dict]:
    try:
        return json.loads(document.pages_json or "[]")
    except json.JSONDecodeError:
        return []
