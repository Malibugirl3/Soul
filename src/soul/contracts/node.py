from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class NodeIdentity(BaseModel):
    """Uniquely identifies a node instance in the federation."""
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str  # "reasoning" | "memory" | "perception" | "action" | custom
    display_name: str = ""
    version: str = "0.1.0"
    host: str = ""
    pid: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NodeRegistration(BaseModel):
    """Node -> Core: "I am here, here is what I do"."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.node.register/1")
    identity: NodeIdentity
    capabilities: List[str] = Field(default_factory=list)
    subscriptions: List[str] = Field(default_factory=list)
    ttl_ms: int = 30000


class NodeStatus(BaseModel):
    """Current status of a registered node."""
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.node.status/1")
    node_id: str
    status: str = "online"  # online | busy | degraded | offline
    last_heartbeat_ts: int = 0
    uptime_ms: int = 0
    metrics: Dict[str, float] = Field(default_factory=dict)
