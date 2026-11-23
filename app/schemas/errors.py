from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["The requested resource was not found."])
    request_id: str | None = Field(default=None, examples=["9f1c2b7e0d4a4e5f8a6b3c2d1e0f9a8b"])
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody
