from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.postgres.models.folder import Folder
from app.schema.folder import FolderCreate, FolderUpdate


class FolderRepository:
    def get_by_id(self, db: Session, folder_id: UUID, user_id: UUID) -> Folder | None:
        return db.execute(
            select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
        ).scalar_one_or_none()

    def get_by_name(self, db: Session, user_id: UUID, name: str) -> Folder | None:
        return db.execute(
            select(Folder).where(Folder.user_id == user_id, Folder.name == name)
        ).scalar_one_or_none()

    def list(self, db: Session, user_id: UUID, skip: int = 0, limit: int = 50) -> list[Folder]:
        return list(
            db.execute(
                select(Folder)
                .where(Folder.user_id == user_id)
                .order_by(Folder.is_pinned.desc(), Folder.updated_at.desc())
                .offset(skip)
                .limit(limit)
            ).scalars().all()
        )

    def create(self, db: Session, user_id: UUID, data: FolderCreate) -> Folder:
        folder = Folder(user_id=user_id, **data.model_dump())
        db.add(folder)
        return folder

    def update(self, db: Session, folder: Folder, payload: FolderUpdate) -> Folder:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(folder, field, value)
        return folder

    def delete(self, db: Session, folder: Folder) -> None:
        db.delete(folder)
