"""Authentication service using UserRepository."""
from __future__ import annotations

import re
from fastapi import Depends, HTTPException, Request, status

from ..models.case import User, Case
from ..repositories.user_repository import user_repository, UserRepository
from ..repositories.case_repository import case_repository
from ..security import create_access_token, decode_token, hash_password, verify_password

ROLES = ["LAWYER", "JUDGE", "LEGAL_INTERN", "LEGAL_RESEARCHER", "LAW_STUDENT", "OTHER"]
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]{2,}$")
CREDENTIALS_MESSAGE = "Invalid email or password."


class AuthError(Exception):
    pass


def signup(payload: dict, repo: UserRepository = user_repository) -> tuple[User, str]:
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
    if repo.get_by_email(email):
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
    repo.create(user)
    return user, create_access_token(user.id, {"email": user.email})


def login(email: str, password: str, repo: UserRepository = user_repository) -> tuple[User, str]:
    user = repo.get_by_email((email or "").strip().lower())
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
        "createdAt": user.created_at,
        "credentialNotice": (
            "Professional credentials provided by the user are not independently "
            "verified by this prototype."
        ),
    }


def get_current_user(request: Request, repo: UserRepository = Depends(lambda: user_repository)) -> User:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    payload = decode_token(header.split(" ", 1)[1].strip())
    if not payload or not payload.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    user = repo.get_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Please sign in again.")
    return user


def owned_case(case_id: str, user: User = Depends(get_current_user)) -> Case:
    case = case_repository.get_by_id(case_id, user_id=user.id)
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Case '{case_id}' was not found.")
    return case
