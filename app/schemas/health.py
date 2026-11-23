from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CheckStatus = Literal["ok", "unavailable"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = Field(examples=["FinLedger API"])
    version: str = Field(examples=["0.1.0"])
    environment: str = Field(examples=["local"])
    timestamp: datetime


class ReadinessResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus] = Field(examples=[{"database": "ok"}])
