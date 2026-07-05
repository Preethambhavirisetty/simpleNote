from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class Role(str, Enum):
    ADMIN = "admin"
    STANDARD_USER = "standard_user"
    ADMIN_USER = "admin_user"


def validate_password_strength(v: str) -> str:
    if len(v) < 6:
        raise ValueError("Password must have atleast 6 characters")
    if not any(c.isupper() for c in v):
        raise ValueError("Password must have at least one uppercase")
    if not any(c.isdigit() or not c.isalnum() for c in v):
        raise ValueError("Password must have atleast one alphanumeric or a special character")
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
    name: Optional[str] = None
    email: Optional[EmailStr] = None


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
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


class UserRegisterResponse(BaseModel):
    name: str
    email: EmailStr
    role: Optional[List[Role]] = Field(default_factory=lambda: [Role.STANDARD_USER])
    is_token_set: bool = False


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str
