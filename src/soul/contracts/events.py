from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .protocol import EventName

class SourceInfo(BaseModel):
    """
    Semantic origin of an event (not tied to any specific frontend/integration).
    Examples:
      kind="user", kind="system", kind="tool", kind="agent"
    """
    model_config = ConfigDict(extra="forbid")

    kind: str
    id: Optional[str] = None
    display: Optional[str] = None   #


class Event(BaseModel):
    """
    Canonical event model used by Soul runtime.

    Key idea:
      - Envelope answers "how it arrived" (transport + message type)
      - Event answers "what happened" (business semantics)
    """
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.event/1")

    name: EventName
    source: SourceInfo
    ts: int     # unix epoch in milliseconds

    text: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    tags: Dict[str, Any] = Field(default_factory=dict)

    priority: int = 0                       # suggested range [-10, 10]
    ttl_ms: Optional[int] = None            # if set, drop events older than ts+ttl
    idempotency_key: Optional[str] = None   # for deduplication

    # TODO: validations : event.name priority ...

    @field_validator("priority")
    @classmethod
    def _priority_range(cls, v: int) -> int:
        if v < -10 or v > 10:
            raise ValueError(f"priority must be in range [-10, 10], got {v}")
        return v