from app.schema.base import ErrorCode


class AppException(Exception):
    """
    Example use case:
        raise AppException(
            message="user not authorized",
            status_code=403,
            error_code="AUTH_PERMISSION_DENIED"
        )
    """
    def __init__(self, message: str, status_code: int, error_code: ErrorCode):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
