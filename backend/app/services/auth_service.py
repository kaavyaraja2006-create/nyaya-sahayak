"""Authentication service and shared request dependencies."""
from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Case, User
from ..security import create_access_token, decode_token, hash_password, verify_password
from . import case_service

ROLES = ["LAWYER", "JUDGE", "LEGAL_INTERN", "LEGAL_RESEARCHER", "LAW_STUDENT", "OTHER"]
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]{2,}$")

CREDENTIALS_MESSAGE = "Invalid email or password."  # never reveals which field failed


class AuthError(Exception):
    pass


def signup(db: Session, payload: dict) -> tuple[User, str]:
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    full_name = (payload.get("fullName") or "").strip()

    if not EMAIL_RE.match(email):
        raise AuthError("Enter a valid email address.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if payload.get("confirmPassword") is not None and payload["confirmPassword"] != password:
        raise AuthError("The passwords do not match.")
    if not full_name:
        raise AuthError("Full name is required.")
    if db.scalar(select(User).where(User.email == email)):
        raise AuthError("An account already exists for this email address.")

    role = (payload.get("role") or "OTHER").upper()
    experience = payload.get("experienceYears")
    try:
        experience = int(experience) if experience not in (None, "") else None
    except (TypeError, ValueError):
        experience = None

    user = User(
        full_name=full_name,
        email=email,
        phone=(payload.get("phone") or "").strip() or None,
        password_hash=hash_password(password),
        role=role if role in ROLES else "OTHER",
        organization=(payload.get("organization") or "").strip() or None,
        registration_number=(payload.get("registrationNumber") or "").strip() or None,
        experience_years=experience,
        specialization=(payload.get("specialization") or "").strip() or None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, create_access_token(user.id, {"email": user.email})


def login(db: Session, email: str, password: str) -> tuple[User, str]:
    user = db.scalar(select(User).where(User.email == (email or "").strip().lower()))
    if user is None or not verify_password(password or "", user.password_hash):
        raise AuthError(CREDENTIALS_MESSAGE)
    return user, create_access_token(user.id, {"email": user.email})


def user_out(user: User) -> dict:
    return {
        "id": user.id,
        "fullName": user.full_name,
        "email": user.email,
        "phone": user.phone or "",
        "role": user.role,
        "organization": user.organization or "",
        "registrationNumber": user.registration_number or "",
        "experienceYears": user.experience_years,
        "specialization": user.specialization or "",
        "createdAt": user.created_at.strftime("%Y-%m-%dT%H:%M:%S") if user.created_at else "",
        "credentialNotice": (
            "Professional credentials provided by the user are not independently "
            "verified by this prototype."
        ),
    }


# ── dependencies ──────────────────────────────────────────────────────────────

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    payload = decode_token(header.split(" ", 1)[1].strip())
    if not payload or not payload.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    return user


def owned_case(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Case:
    try:
        return case_service.get_owned_case(db, user.id, case_id)
    except case_service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
