from uuid import UUID

from sqlalchemy.orm import Session

from app.core.security import check_password, hash_password
from app.db.postgres.repos.user import UserRepository
from app.exceptions.base import AppException
from app.schema.base import ErrorCode
from app.schema.users import UserAssignRoles, UserChangePassword, UserCreate, UserUpdate


class UserService:
    def __init__(self):
        self.user_repo = UserRepository()

    def _get_user_or_404(self, db: Session, user_id: UUID):
        user = self.user_repo.get_by_id(db, user_id)
        if not user:
            raise AppException(
                message="User not found",
                status_code=404,
                error_code=ErrorCode.USER_NOT_FOUND,
            )
        return user

    def _parse_uuid(self, user_id) -> UUID:
        try:
            return UUID(str(user_id))
        except ValueError:
            raise AppException(
                message="Invalid user id",
                status_code=400,
                error_code=ErrorCode.VALIDATION_ERROR,
            )

    # ── CRUD ──────────────────────────────────────────────────────────────
    def create_user(self, db: Session, user_data: UserCreate):
        if self.user_repo.get_by_email(db, user_data.email):
            raise AppException(
                message="User with this email already exists",
                status_code=400,
                error_code=ErrorCode.REGISTRATION_FAILED,
            )
        user = self.user_repo.create(db, user_data)
        db.commit()
        db.refresh(user)
        return user

    def get_user(self, db: Session, user_id):
        return self._get_user_or_404(db, self._parse_uuid(user_id))

    def list_users(self, db: Session, skip: int = 0, limit: int = 50):
        return self.user_repo.list(db, skip=skip, limit=limit)

    def update_user(self, db: Session, user_id, payload: UserUpdate):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        self.user_repo.update(db, user, payload)
        db.commit()
        db.refresh(user)
        return user

    def delete_user(self, db: Session, user_id):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        self.user_repo.delete(db, user)
        db.commit()

    # ── password ─────────────────────────────────────────────────────────
    def change_password(self, db: Session, user_id, payload: UserChangePassword):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        if not check_password(payload.current_password, user.hashed_password):
            raise AppException(
                message="Current password is incorrect",
                status_code=400,
                error_code=ErrorCode.INVALID_CREDENTIALS,
            )
        self.user_repo.update_password(db, user, hash_password(payload.new_password))
        db.commit()

    # ── roles ─────────────────────────────────────────────────────────────
    def assign_roles(self, db: Session, user_id, payload: UserAssignRoles):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        self.user_repo.assign_roles(db, user, [r.value for r in payload.roles])
        db.commit()
        db.refresh(user)
        return user

    # ── active state ──────────────────────────────────────────────────────
    def activate_user(self, db: Session, user_id):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        self.user_repo.set_active(db, user, True)
        db.commit()

    def deactivate_user(self, db: Session, user_id):
        user = self._get_user_or_404(db, self._parse_uuid(user_id))
        self.user_repo.set_active(db, user, False)
        db.commit()
