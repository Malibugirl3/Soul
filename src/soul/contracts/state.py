from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class Utterance(BaseModel):
    """
    A single message in short-term working memory.
    """
    model_config = ConfigDict(extra="forbid")

    role: str
    text: str
    ts: int 


class ModeState(BaseModel):
    """
    High-level operating mode of Soul.
    """
    model_config = ConfigDict(extra="forbid")

    name: str = "idle"
    since_ts: int = 0           # when this mode was entered
    confidence: float = 1.0     # confidence of this mode


class DialogState(BaseModel):
    """
    Short-term conversation context (working memory).
    """
    model_config = ConfigDict(extra="forbid")

    turn_index: int = 0
    last_user_text: Optional[str] = None
    last_assistant_text: Optional[str] = None
    working_memory: List[Utterance] = Field(default_factory=list)
    topic: Optional[str] = None


class MemoryState(BaseModel):
    """
    Long-term memory metadata: summary/facts/pointers only.
    (Action storage handeld by memory capability later.)
    """
    model_config = ConfigDict(extra="forbid")

    summary: Optional[str] = None
    facts: List[str] = Field(default_factory=list)
    pointers: Dict[str, str] = Field(default_factory=dict)


class SoulState(BaseModel):
    """
    Canonical session state for Soul runtime.
    """
    model_config = ConfigDict(extra="forbid")

    schema_id: str = Field(default="soul.memory/1")
    session_id: str

    mode: ModeState = Field(default_factory=ModeState)
    dialog: DialogState = Field(default_factory=DialogState)
    memory: MemoryState = Field(default_factory=MemoryState)

    flags: Dict[str, bool] = Field(default_factory=dict)
    vars: Dict[str, Any] = Field(default_factory=dict)          # 干什么的


class StatePatch(BaseModel):
    """
    Patch semantics for state updates.
    Use dot-path keys like "mode.name"
    """
    model_config = ConfigDict(extra="forbid")

    set: Dict[str, Any] = Field(default_factory=dict)
    unset: List[str] = Field(default_factory=list)
    inc: Dict[str, float] = Field(default_factory=dict)