"""Authentication, case, document and transcript routes."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Case, User
from ..services import auth_service, case_service
from ..services.auth_service import AuthError, get_current_user, owned_case
from ..services.case_service import DOCUMENT_TYPES, NotFound
from ..utils.files import UploadRejected
from ..utils.serialize import case_out, document_out, document_summary, transcript_out

auth_router = APIRouter(prefix="/auth", tags=["auth"])
case_router = APIRouter(prefix="/cases", tags=["cases"])


# ── auth ──────────────────────────────────────────────────────────────────────

@auth_router.post("/signup", status_code=201)
def signup(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    try:
        user, token = auth_service.signup(db, payload)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"token": token, "tokenType": "bearer", "user": auth_service.user_out(user)}


@auth_router.post("/login")
def login(payload: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    try:
        user, token = auth_service.login(db, payload.get("email", ""), payload.get("password", ""))
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return {"token": token, "tokenType": "bearer", "user": auth_service.user_out(user)}


@auth_router.post("/logout")
def logout(user: User = Depends(get_current_user)) -> dict:
    # Tokens are stateless; the client discards it. Recorded for completeness.
    return {"ok": True}


@auth_router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return auth_service.user_out(user)


@auth_router.put("/me")
def update_me(payload: dict = Body(...), user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> dict:
    for key, attr in (
        ("fullName", "full_name"), ("phone", "phone"), ("organization", "organization"),
        ("registrationNumber", "registration_number"), ("specialization", "specialization"),
    ):
        if key in payload and isinstance(payload[key], str):
            setattr(user, attr, payload[key].strip() or None)
    if payload.get("role") in auth_service.ROLES:
        user.role = payload["role"]
    db.commit()
    db.refresh(user)
    return auth_service.user_out(user)


# ── cases ─────────────────────────────────────────────────────────────────────

@case_router.get("")
def list_cases(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    return [case_out(c, case_service.case_counts(db, c.id)) for c in case_service.list_cases(db, user)]


@case_router.post("", status_code=201)
def create_case(payload: dict = Body(...), db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    if not (payload.get("name") or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Case name is required.")
    case = case_service.create_case(db, user, payload)
    return case_out(case, case_service.case_counts(db, case.id))


@case_router.get("/{case_id}")
def get_case(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> dict:
    return case_out(case, case_service.case_counts(db, case.id))


@case_router.put("/{case_id}")
def update_case(payload: dict = Body(...), case: Case = Depends(owned_case),
                db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    case = case_service.update_case(db, case, payload, user)
    return case_out(case, case_service.case_counts(db, case.id))


@case_router.delete("/{case_id}", status_code=204)
def delete_case(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> None:
    case_service.delete_case(db, case)


@case_router.get("/{case_id}/bundle")
def bundle(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> dict:
    from ..services import report_service

    return report_service.build_bundle(db, case)


# ── documents ─────────────────────────────────────────────────────────────────

@case_router.get("/{case_id}/documents")
def list_documents(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [document_summary(d) for d in case_service.list_documents(db, case.id)]


@case_router.post("/{case_id}/documents", status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    documentType: str = Form("Other"),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stored, rejected = [], []
    for upload in files:
        data = await upload.read()
        try:
            document = case_service.store_document(
                db, case, user,
                filename=upload.filename or "document",
                content_type=upload.content_type,
                data=data,
                document_type=documentType,
            )
            stored.append(document_summary(document))
        except UploadRejected as exc:
            rejected.append({"filename": upload.filename, "reason": str(exc)})
    if not stored and rejected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, rejected[0]["reason"])
    return {"documents": stored, "rejected": rejected}


@case_router.get("/{case_id}/documents/{document_id}")
def get_document(document_id: str, case: Case = Depends(owned_case),
                 db: Session = Depends(get_db)) -> dict:
    try:
        return document_out(case_service.get_document(db, case.id, document_id))
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@case_router.get("/{case_id}/documents/{document_id}/file")
def download_document(document_id: str, case: Case = Depends(owned_case),
                      db: Session = Depends(get_db)) -> FileResponse:
    try:
        document = case_service.get_document(db, case.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return FileResponse(document.storage_path, filename=document.filename)


@case_router.delete("/{case_id}/documents/{document_id}", status_code=204)
def delete_document(document_id: str, case: Case = Depends(owned_case),
                    db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    try:
        document = case_service.get_document(db, case.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    case_service.delete_document(db, document, user)


@case_router.get("/{case_id}/document-types")
def document_types(case: Case = Depends(owned_case)) -> list[str]:
    return DOCUMENT_TYPES


# ── transcripts ───────────────────────────────────────────────────────────────

@case_router.get("/{case_id}/transcripts")
def list_transcripts(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> list[dict]:
    return [transcript_out(t) for t in case_service.list_transcripts(db, case.id)]


@case_router.post("/{case_id}/transcripts", status_code=201)
async def upload_transcript(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    hearingDate: str = Form(""),
    hearingNumber: str = Form(""),
    court: str = Form(""),
    case: Case = Depends(owned_case),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    data = await file.read() if file is not None else None
    try:
        transcript = case_service.create_transcript(
            db, case, user,
            hearing_date=hearingDate or None,
            hearing_number=hearingNumber or None,
            court=court or None,
            filename=file.filename if file else None,
            content_type=file.content_type if file else None,
            data=data,
            pasted_text=text,
        )
    except (UploadRejected, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return transcript_out(transcript)


@case_router.get("/{case_id}/hearing")
def get_hearing(case: Case = Depends(owned_case), db: Session = Depends(get_db)) -> dict | None:
    transcripts = case_service.list_transcripts(db, case.id)
    return transcript_out(transcripts[0]) if transcripts else None
