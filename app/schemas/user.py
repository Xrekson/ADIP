from pydantic import BaseModel, EmailStr
from app.models.user import UserRole

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: UserRole = UserRole.BIDDER

class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    model_config = {"from_attributes": True}

class Token(BaseModel):
    access_token: str
    token_type: str