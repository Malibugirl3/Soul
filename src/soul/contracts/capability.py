from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .protocol import UrgencyLevel


class ActionSchema(BaseModel):
    """Describes one action a node can perform. The `schema` is JSON Schema
    for the action's params — the ReasoningNode uses these to decide what to invoke."""
    model_config = ConfigDict(extra="forbid")

    action_type: str
    description: str
    params_schema: Dict[str, Any] = Field(default_factory=dict)
    urgency: UrgencyLevel = UrgencyLevel.soon
    ttl_ms: Optional[int] = None
    idempotent: bool = False


class CapabilityManifest(BaseModel):
    """Full capability announcement from a node to the Core."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.capability/1")
    node_id: str
    actions: List[ActionSchema] = Field(default_factory=list)
    version: str = "1"
    ts: int = 0
