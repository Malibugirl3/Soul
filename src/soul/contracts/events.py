from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceInfo(BaseModel):
    """Semantic origin of an event."""
    model_config = ConfigDict(extra="forbid")

    kind: str  # user | system | tool | agent
    id: Optional[str] = None
    display: Optional[str] = None


class Event(BaseModel):
    """
    Canonical event model. Event names are extensible — any string is valid.
    Known names are defined as constants in protocol.py (EventName class).
    """
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.event/1")

    name: str
    source: SourceInfo
    ts: int  # unix epoch in milliseconds

    text: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    tags: Dict[str, Any] = Field(default_factory=dict)

    priority: int = 0  # range [-10, 10]
    ttl_ms: Optional[int] = None
    idempotency_key: Optional[str] = None

    @field_validator("priority")
    @classmethod
    def _priority_range(cls, v: int) -> int:
        if v < -10 or v > 10:
            raise ValueError(f"priority must be in range [-10, 10], got {v}")
        return v