from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from ..contracts.events import Event
from ..contracts.response import Response, Action
from ..contracts.state import SoulState
from ..contracts.node import NodeIdentity
from ..contracts.capability import ActionSchema

from .base import BaseNode


class PerceptionNode(BaseNode):
    """Enriches events with temporal context, session stats, and basic meta."""

    def __init__(
        self,
        node_id: str = "perception-01",
        tz_name: str = "Asia/Shanghai",
        standalone: bool = False,
    ) -> None:
        identity = NodeIdentity(
            node_id=node_id,
            node_type="perception",
            display_name="Perception Node",
        )
        super().__init__(identity, standalone=standalone)
        self.tz_name = tz_name
        self._session_turns: Dict[str, int] = {}
        self._session_start: Dict[str, int] = {}

    def _action_schemas(self) -> List[ActionSchema]:
        return [
            ActionSchema(
                action_type="perception.enrich",
                description="Enrich an event with temporal and session context",
                params_schema={
                    "type": "object",
                    "properties": {
                        "timezone": {"type": "string"},
                    },
                },
            ),
            ActionSchema(
                action_type="perception.get_time_context",
                description="Get detailed time context",
                params_schema={"type": "object", "properties": {}},
            ),
        ]

    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        now = datetime.now(timezone.utc)
        hour = now.hour
        if hour < 6:
            time_of_day = "night"
        elif hour < 12:
            time_of_day = "morning"
        elif hour < 18:
            time_of_day = "afternoon"
        else:
            time_of_day = "evening"

        s_turns = self._session_turns
        s_start = self._session_start

        sid = "default"
        if state:
            sid = state.session_id
            s_turns[sid] = state.dialog.turn_index
            if sid not in s_start:
                s_start[sid] = event.ts

        perception_ctx = {
            "iso_time": now.isoformat(),
            "time_of_day": time_of_day,
            "day_of_week": now.strftime("%A"),
            "tz": self.tz_name,
            "turn_count": s_turns.get(sid, 0),
            "session_age_ms": event.ts - s_start.get(sid, event.ts),
        }

        return Response(
            ts=event.ts,
            text="",
            data={"perception": perception_ctx},
        )
