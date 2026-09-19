"""Authentication, case, document and transcript routes using PyMongo services."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from ..config import settings
from ..models.case import Case, User
from ..services import auth_service, case_service
from ..services.auth_service import AuthError, get_current_user, owned_case
from ..services.case_service import DOCUMENT_TYPES, NotFound
from ..utils.files import UploadRejected

auth_router = APIRouter(prefix="/auth", tags=["auth"])
case_router = APIRouter(prefix="/cases", tags=["cases"])


# ── auth ──────────────────────────────────────────────────────────────────────

@auth_router.post("/signup", status_code=201)
def signup(payload: dict = Body(...)) -> dict:
    try:
        user, token = auth_service.signup(payload)
    except AuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"token": token, "tokenType": "bearer", "user": auth_service.user_out(user)}


@auth_router.post("/login")
def login(payload: dict = Body(...)) -> dict:
    try:
        user, token = auth_service.login(payload.get("email", ""), payload.get("password", ""))
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    return {"token": token, "tokenType": "bearer", "user": auth_service.user_out(user)}


@auth_router.post("/logout")
def logout(user: User = Depends(get_current_user)) -> dict:
    return {"ok": True}


@auth_router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return auth_service.user_out(user)


@auth_router.put("/me")
def update_me(payload: dict = Body(...), user: User = Depends(get_current_user)) -> dict:
    for key, attr in (
        ("fullName", "full_name"),
        ("phone", "phone"),
        ("organization", "organization"),
        ("registrationNumber", "registration_number"),
        ("specialization", "specialization"),
    ):
        if key in payload and isinstance(payload[key], str):
            setattr(user, attr, payload[key].strip() or None)
    if payload.get("role") in auth_service.ROLES:
        user.role = payload["role"]
    auth_service.user_repository.update(user)
    return auth_service.user_out(user)


# ── cases ─────────────────────────────────────────────────────────────────────

@case_router.get("")
def list_cases(user: User = Depends(get_current_user)) -> list[dict]:
    cases = case_service.list_cases(user)
    return [c.to_dict() for c in cases]


@case_router.post("", status_code=201)
def create_case(payload: dict = Body(...), user: User = Depends(get_current_user)) -> dict:
    if not (payload.get("name") or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Case name is required.")
    case = case_service.create_case(user, payload)
    return case.to_dict()


@case_router.get("/{case_id}")
def get_case(case: Case = Depends(owned_case)) -> dict:
    return case.to_dict()


@case_router.put("/{case_id}")
def update_case(payload: dict = Body(...), case: Case = Depends(owned_case), user: User = Depends(get_current_user)) -> dict:
    updated = case_service.update_case(case, payload, user)
    return updated.to_dict()


@case_router.delete("/{case_id}", status_code=204)
def delete_case(case: Case = Depends(owned_case)) -> None:
    case_service.delete_case(case)


# ── documents ─────────────────────────────────────────────────────────────────

@case_router.get("/{case_id}/documents")
def list_documents(case: Case = Depends(owned_case)) -> list[dict]:
    docs = case_service.list_documents(case.id)
    return [d.to_dict() for d in docs]


@case_router.post("/{case_id}/documents", status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    documentType: str = Form("Other"),
    case: Case = Depends(owned_case),
    user: User = Depends(get_current_user),
) -> dict:
    stored, rejected = [], []
    for upload in files:
        data = await upload.read()
        try:
            document = case_service.store_document(
                case,
                user,
                filename=upload.filename or "document",
                content_type=upload.content_type,
                data=data,
                document_type=documentType,
            )
            stored.append(document.to_dict())
        except UploadRejected as exc:
            rejected.append({"filename": upload.filename, "reason": str(exc)})
    if not stored and rejected:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, rejected[0]["reason"])
    return {"documents": stored, "rejected": rejected}


@case_router.get("/{case_id}/documents/{document_id}")
def get_document(document_id: str, case: Case = Depends(owned_case)) -> dict:
    try:
        doc = case_service.get_document(case.id, document_id)
        return doc.to_dict()
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@case_router.get("/{case_id}/documents/{document_id}/file")
def download_document(document_id: str, case: Case = Depends(owned_case)) -> FileResponse:
    try:
        document = case_service.get_document(case.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return FileResponse(document.storage_path, filename=document.filename)


@case_router.delete("/{case_id}/documents/{document_id}", status_code=204)
def delete_document(document_id: str, case: Case = Depends(owned_case), user: User = Depends(get_current_user)) -> None:
    try:
        document = case_service.get_document(case.id, document_id)
    except NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    case_service.delete_document(document, user)


@case_router.get("/{case_id}/document-types")
def document_types(case: Case = Depends(owned_case)) -> list[str]:
    return DOCUMENT_TYPES
