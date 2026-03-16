from uuid import UUID
from sqlalchemy import select

from app.db.postgres.models.user import User
import app.db.postgres.session as pg_session
from app.exceptions.base import AppException
from app.schema.base import ErrorCode


class UserService:
    async def get_user_by_id(self, user_id):
        try:
            if pg_session.SessionLocal is None:
                raise AppException(
                    message="Postgres is not configured",
                    status_code=500,
                    error_code=ErrorCode.INTERNAL_SERVER_ERROR,
                )

            user_uuid = UUID(str(user_id))
            with pg_session.SessionLocal() as db:
                stmt = select(User).where(User.id == user_uuid)
                return db.execute(stmt).scalar_one_or_none()

        except ValueError:
            raise AppException(
                message="Invalid user id",
                status_code=401,
                error_code=ErrorCode.UNAUTHORIZED,
            )
        except AppException:
            raise
        except Exception:
            raise AppException(
                message="Failed to fetch user",
                status_code=500,
                error_code=ErrorCode.INTERNAL_SERVER_ERROR,
            )
