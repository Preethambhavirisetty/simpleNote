from fastapi import Request, HTTPException 
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.schema.base import ErrorCode
from app.exceptions.base import AppException

def register_exceptions(app):

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.message,
                "data": None,
                "error": {"code": exc.error_code}
            }
        )
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.detail,
                "data": None,
                "error": {"code": ErrorCode.HTTP_ERROR},
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        errors = [
            {
                "field": " -> ".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "Validation error",
                "data": None,
                "error": errors,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "Internal server error",
                "data": None,
                "error": {"code": ErrorCode.INTERNAL_SERVER_ERROR},
            },
        )


def success_response(data=None, message="Success"):
    return {
        "success": True,
        "message": message,
        "data": data,
        "error": None
    }