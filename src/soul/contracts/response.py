from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .state import StatePatch
from .protocol import UrgencyLevel


class Action(BaseModel):
    """Abstract intent produced by Soul. Not UI commands."""
    model_config = ConfigDict(extra="forbid")

    type: str
    params: Dict[str, Any] = Field(default_factory=dict)

    node_id: Optional[str] = None
    urgency: UrgencyLevel = UrgencyLevel.soon

    when: Optional[str] = None
    idempotency_key: Optional[str] = None
    requires: List[str] = Field(default_factory=list)


class Response(BaseModel):
    """Canonical output from Soul runtime for one event."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.response/1")
    ts: int

    text: str
    actions: List[Action] = Field(default_factory=list)
    data: Dict[str, Any] = Field(default_factory=dict)

    state_patch: Optional[StatePatch] = None
    debug: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, float]] = None
