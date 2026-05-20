from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field

from .protocol import SparkVerb, UrgencyLevel


class SparkMessage(BaseModel):
    """Inter-node signal routed through the Core bus.

    notify = fire-and-forget
    command = request-reply (correlation_id used to match)
    emit = broadcast to all nodes of target_type (or all if None)
    """
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.spark/1")
    verb: SparkVerb
    source_node: str
    target_node: Optional[str] = None
    target_type: Optional[str] = None
    urgency: UrgencyLevel = UrgencyLevel.soon
    action: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None
    ts: int = 0
    ttl_ms: Optional[int] = None
