"""Case, document, transcript and audit services using MongoDB Repositories."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..models.case import Case, User
from ..models.document import Document
from ..models.audit import AuditEvent
from ..repositories import (
    case_repository,
    document_repository,
    claim_repository,
    evidence_repository,
    relationship_repository,
    conflict_repository,
    authority_repository,
    citation_repository,
    review_repository,
    audit_repository,
)
from ..utils import files as fileutil
from ..utils.ids import next_index, seq_id


class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


# ── audit ─────────────────────────────────────────────────────────────────────

def log_event(
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
) -> AuditEvent:
    events = audit_repository.list_by_case(case_row_id)
    count = len(events)
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
    audit_repository.create(event)
    return event


def list_audit(case_row_id: str) -> list[AuditEvent]:
    return audit_repository.list_by_case(case_row_id)


# ── cases ─────────────────────────────────────────────────────────────────────

def next_case_public_id() -> str:
    year = datetime.now().year
    prefix = f"NS-{year}-"
    all_cases = case_repository.find_many({"case_id": {"$regex": f"^{prefix}"}})
    existing = [c.get("case_id", "") for c in all_cases]
    numbers = [int(v.rsplit("-", 1)[1]) for v in existing if "-" in v and v.rsplit("-", 1)[1].isdigit()]
    return f"{prefix}{str(max(numbers, default=0) + 1).zfill(3)}"


def create_case(user: User, payload: dict) -> Case:
    case = Case(
        case_id=next_case_public_id(),
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
    case_repository.create(case)
    log_event(
        case.id,
        action="Case created",
        object_type="case",
        object_id=case.case_id,
        actor=user.full_name,
        actor_type="reviewer",
        new_state="DRAFT",
        details=f"Case '{case.name}' created.",
    )
    return case


def list_cases(user: User) -> list[Case]:
    return case_repository.list_by_user(user.id)


def get_owned_case(user_id: str, case_public_id: str) -> Case:
    """The single ownership gate. Every case-scoped read and write goes through it."""
    case = case_repository.get_by_id(case_public_id)
    if case is None:
        raise NotFound(f"No case was found for the supplied case_id '{case_public_id}'.")
    if case.user_id != user_id:
        raise NotFound(f"No case was found for the supplied case_id '{case_public_id}'.")
    return case


def case_counts(case_row_id: str) -> dict:
    docs = document_repository.list_by_case(case_row_id)
    claims = claim_repository.list_by_case(case_row_id)
    evidence = evidence_repository.list_by_case(case_row_id)
    relationships = relationship_repository.list_by_case(case_row_id)
    conflicts = conflict_repository.list_by_case(case_row_id)
    reviews = review_repository.list_by_case(case_row_id)
    citations = citation_repository.list_by_case(case_row_id)

    return {
        "documents": len([d for d in docs if not d.is_transcript]),
        "transcripts": len([d for d in docs if d.is_transcript]),
        "claims": len(claims),
        "evidence": len(evidence),
        "relationships": len(relationships),
        "conflicts": len([c for c in conflicts if c.kind == "conflict"]),
        "findings": len(conflicts),
        "citations": len(citations),
        "reviews": len(reviews),
        "reports": 0,
        "openFindings": len([c for c in conflicts if c.status == "open"]),
    }


def update_case(case: Case, payload: dict, user: User) -> Case:
    mapping = {
        "name": "name",
        "caseNumber": "case_number",
        "caseType": "case_type",
        "jurisdiction": "jurisdiction",
        "court": "court",
        "description": "description",
        "status": "status",
        "filedOn": "filed_on",
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
            case.id,
            action="Case details updated",
            object_type="case",
            object_id=case.case_id,
            actor=user.full_name,
            actor_type="reviewer",
            details=f"Updated: {', '.join(changed)}",
        )
    case_repository.update(case)
    return case


def delete_case(case: Case) -> None:
    case_repository.delete(case.id, case.user_id)


def set_status(case: Case, status: str, actor: str = "System") -> None:
    previous = case.status
    if previous == status:
        return
    case.status = status
    log_event(
        case.id,
        action="Case status changed",
        object_type="case",
        object_id=case.case_id,
        actor=actor,
        actor_type="system",
        previous_state=previous,
        new_state=status,
    )
    case_repository.update(case)


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


def next_document_id(case_row_id: str) -> str:
    docs = document_repository.list_by_case(case_row_id)
    existing = [d.document_id for d in docs]
    return seq_id("DOC", next_index(existing, "DOC"), 3)


def store_document(
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
        document_id=next_document_id(case.id),
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
    document_repository.create(document)
    process_document(document)
    log_event(
        case.id,
        action="Transcript uploaded" if is_transcript else "Document uploaded",
        object_type="document",
        object_id=document.document_id,
        actor=user.full_name,
        actor_type="reviewer",
        details=f"{document.filename} ({document.page_count} page(s)) indexed.",
    )
    return document


def process_document(document: Document) -> None:
    """Extract pages, paragraphs and entities. Original file is always retained."""
    try:
        pages = fileutil.extract_pages(Path(document.storage_path))
        document.pages_json = pages
        document.page_count = len(pages)
        document.extracted_text = fileutil.pages_to_text(pages)
        document.status = "indexed" if any(p.get("paragraphs") for p in pages) else "needs_review"
    except Exception as exc:  # noqa: BLE001
        document.status = "error"
        document.pages_json = []
        document.extracted_text = ""
        document.page_count = 0
        _ = exc
    document_repository.update(document)


def list_documents(case_row_id: str) -> list[Document]:
    return document_repository.list_by_case(case_row_id)


def get_document(case_row_id: str, document_public_id: str) -> Document:
    doc = document_repository.get_by_id(document_public_id, case_id=case_row_id)
    if doc is None:
        raise NotFound(f"No document was found for '{document_public_id}'.")
    return doc


def delete_document(document: Document, user: User) -> None:
    try:
        Path(document.storage_path).unlink(missing_ok=True)
    except OSError:
        pass
    log_event(
        document.case_id,
        action="Document removed",
        object_type="document",
        object_id=document.document_id,
        actor=user.full_name,
        actor_type="reviewer",
    )
    document_repository.delete(document.id, document.case_id)


def document_pages(document: Document) -> list[dict]:
    if isinstance(document.pages_json, list):
        return document.pages_json
    try:
        return json.loads(document.pages_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
