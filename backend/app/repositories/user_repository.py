"""User MongoDB repository."""
from __future__ import annotations

from typing import Any
from ..models.case import User
from .base_repository import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self) -> None:
        super().__init__("users")

    def get_by_id(self, user_id: str) -> User | None:
        raw = self.find_one({"id": user_id})
        return User.from_dict(raw) if raw else None

    def get_by_email(self, email: str) -> User | None:
        raw = self.find_one({"email": email.strip().lower()})
        return User.from_dict(raw) if raw else None

    def create(self, user: User) -> User:
        user_dict = user.to_dict()
        user_dict["email"] = user_dict["email"].strip().lower()
        self.insert(user_dict)
        return user

    def update(self, user: User) -> User:
        user_dict = user.to_dict()
        user_dict["email"] = user_dict["email"].strip().lower()
        self.update_one({"id": user.id}, user_dict)
        return user


user_repository = UserRepository()
