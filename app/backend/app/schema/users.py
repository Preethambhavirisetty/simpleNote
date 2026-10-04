from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

MAX_PASSWORD_BYTES = 72


class Role(str, Enum):
    ADMIN = "admin"
    STANDARD_USER = "standard_user"
    ADMIN_USER = "admin_user"


def validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must have at least 8 characters")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must have at least one uppercase letter")
    if not any(c.isdigit() or (not c.isalnum() and not c.isspace()) for c in v):
        raise ValueError("Password must have at least one digit or non-alphanumeric character")
    return v


class UserBase(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    role: list[Role] = Field(default_factory=lambda: [Role.STANDARD_USER])


class UserCreate(BaseModel):
    name: str
    email: str
    hashed_password: str
    role: list[str]


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None


class UserChangePassword(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserAssignRoles(BaseModel):
    roles: List[Role]


class UserRegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_BYTES)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must not exceed {MAX_PASSWORD_BYTES} UTF-8 bytes")
        return validate_password_strength(v)


class UserRegisterResponse(BaseModel):
    name: str
    email: EmailStr
    role: Optional[List[Role]] = Field(default_factory=lambda: [Role.STANDARD_USER])
    is_token_set: bool = False


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str
