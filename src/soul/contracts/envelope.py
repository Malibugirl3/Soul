from __future__ import annotations  # 这个是为了支持自引用类型 例如 Envelope -> Envelope

from typing import Any, Dict, Optional  
from pydantic import BaseModel, ConfigDict, Field   

from .protocol import MessageType, PROTOCOL_VERSION

class TraceContext(BaseModel):
    """
    Observability context for tracing/debbuging.
    """
    # 
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    tags: Optional[Dict[str, str]] = None   # 标签，用于添加额外的上下文信息


class Envelope(BaseModel):
    """
    Transport-agnostic envelope. Payload is decoded/validated later based on 'type'.
    """
    model_config = ConfigDict(extra="forbid")

    v: str = Field(default=PROTOCOL_VERSION)
    type: MessageType
    id: str
    ts: int     # unix epoch in milliseconds
    session_id: str
    trace: Optional[TraceContext] = None
    payload: Dict[str, Any]     # 