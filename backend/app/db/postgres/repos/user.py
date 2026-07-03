from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres.models.user import User
from app.schema.users import UserCreate, UserUpdate


class UserRepository:
    def get_by_id(self, db: Session, user_id: UUID) -> User | None:
        return db.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

    def get_by_email(self, db: Session, email: str) -> User | None:
        return db.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

    def list(self, db: Session, skip: int = 0, limit: int = 50) -> list[User]:
        return list(
            db.execute(select(User).offset(skip).limit(limit)).scalars().all()
        )

    def create(self, db: Session, user_data: UserCreate) -> User:
        user = User(**user_data.model_dump())
        db.add(user)
        return user

    def update(self, db: Session, user: User, payload: UserUpdate) -> User:
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(user, field, value)
        return user

    def update_password(self, db: Session, user: User, hashed_password: str) -> User:
        user.hashed_password = hashed_password
        return user

    def assign_roles(self, db: Session, user: User, roles: list[str]) -> User:
        user.role = roles
        return user

    def set_active(self, db: Session, user: User, is_active: bool) -> User:
        user.is_active = is_active
        return user

    def delete(self, db: Session, user: User) -> None:
        db.delete(user)
