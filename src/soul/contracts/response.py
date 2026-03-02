from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from .state import StatePatch


class Action(BaseModel):
    """
    Abstract intent produced by Soul.
    Not Ui commands. Execution is handeld by adapters/integrations later.
    """
    model_config = ConfigDict(extra="forbid")

    type: str
    params: Dict[str, Any] = Field(default_factory=dict)

    # scheduling / execution hints (optional)
    when: Optional[str] = None  
    idempotency_key: Optional[str] = None
    requires: List[str] = Field(default_factory=list)


class Response(BaseModel):
    """
    Canonical output from Soul runtime for one event.
    """
    model_config = ConfigDict(extra="forbid")
    
    schema_id: str = Field(default="soul.response/1")
    ts: int

    text: str
    actions: List[Action] = Field(default_factory=list)

    state_patch: Optional[StatePatch] = None
    debug: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, float]] = None
