from typing import List, Optional
from enum import Enum
from pydantic import Field, EmailStr, BaseModel, field_validator


class Role(str, Enum):
    ADMIN = "admin"
    STANDARD_USER = "standard_user"
    ADMIN_USER = "admin_user"


class UserRegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: Optional[List[Role]] = Field(default_factory=lambda: [Role.STANDARD_USER])

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must have atleast 6 characters")
        if v.islower():
            raise ValueError("Password must have at least one uppercase")
        if v.isalpha() or v.isnumeric():
            raise ValueError("Password must have atleast one alphanumeric or a special character")
        return v


class UserRegisterResponse(BaseModel):
    name: str
    email: EmailStr
    role: Optional[List[Role]] = Field(default_factory=lambda: [Role.STANDARD_USER])
    is_token_set: bool = False


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str
