from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .state import SoulState, StatePatch


class StateSubscription(BaseModel):
    """Node subscribes to state change notifications for specific dot-paths."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.subscription/1")
    node_id: str
    paths: List[str] = Field(default_factory=list)  # e.g. ["dialog.*", "mode.name"]
    filter_op: Optional[str] = None


class StateChangeNotification(BaseModel):
    """Core notifies subscriber after a state change has been applied."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.state_notify/1")
    session_id: str
    state_version: int
    patches: List[StatePatch] = Field(default_factory=list)
    full_snapshot: Optional[SoulState] = None
    ts: int = 0
