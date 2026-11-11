from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool = False


class UserInDB(User):
    hashed_password: str
