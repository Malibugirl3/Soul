from __future__ import annotations

import warnings
from typing import Optional

warnings.warn(
    "runtime.Router is deprecated. Use core.Router instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ..contracts.envelope import Envelope
from ..contracts.protocol import MessageType
from ..contracts.events import Event
from ..contracts.response import Response
from ..contracts.state import SoulState
from .engine import SoulEngine


class Router:
    """
    Dispatch by envelope.type and normalize payload into canonical models.
    """
    def __init__(self, engine: SoulEngine) -> None:
        self.engine = engine

    def route(self, state: SoulState, env: Envelope) -> Optional[Response]:
        if env.type == MessageType.event:
            event = Event.model_validate(env.payload)
            _, resp = self.engine.handle_event(state, event)
            return resp
        
        if env.type == MessageType.heartbeat:
            return Response(ts=env.ts, text="pong")
        
        
        return Response(ts=env.ts, text=f"unsupported type: {env.type}")