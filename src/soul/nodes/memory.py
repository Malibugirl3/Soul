from __future__ import annotations

from typing import Dict, List, Optional

from ..contracts.events import Event
from ..contracts.response import Response, Action
from ..contracts.state import SoulState, Utterance
from ..contracts.protocol import MAX_WORKING_MEMORY
from ..contracts.node import NodeIdentity
from ..contracts.capability import ActionSchema

from .base import BaseNode


class MemoryNode(BaseNode):
    """Manages working memory (conversation buffer) and long-term facts.

    In standalone mode, holds state in memory. Subscribes to state changes
    to auto-capture conversation turns.
    """

    def __init__(
        self,
        node_id: str = "memory-01",
        max_working_memory: int = MAX_WORKING_MEMORY,
        standalone: bool = False,
    ) -> None:
        identity = NodeIdentity(
            node_id=node_id,
            node_type="memory",
            display_name="Memory Node",
        )
        super().__init__(identity, standalone=standalone)
        self.max_working = max_working_memory
        self._working: Dict[str, List[Utterance]] = {}
        self._facts: Dict[str, Dict[str, str]] = {}
        self._summaries: Dict[str, str] = {}

    def _action_schemas(self) -> List[ActionSchema]:
        return [
            ActionSchema(
                action_type="memory.write",
                description="Store a fact in long-term memory. Params: key (str), value (str)",
                params_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["key", "value"],
                },
            ),
            ActionSchema(
                action_type="memory.read",
                description="Read facts from long-term memory. Params: key (str, optional — omit to read all)",
                params_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                },
            ),
            ActionSchema(
                action_type="memory.summarize",
                description="Get a summary of recent conversation",
                params_schema={"type": "object", "properties": {}},
            ),
            ActionSchema(
                action_type="memory.forget",
                description="Remove a specific memory. Params: key (str)",
                params_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                    },
                    "required": ["key"],
                },
            ),
        ]

    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        sid = state.session_id if state else "default"

        # Capture user utterance into working memory
        if event.text:
            wm = self._working.setdefault(sid, [])
            wm.append(Utterance(role="user", text=event.text, ts=event.ts))
            if len(wm) > self.max_working:
                self._working[sid] = wm[-self.max_working :]

        # Build memory context
        memory_ctx = {
            "facts": self._get_all_facts(sid),
            "summary": self._summaries.get(sid, ""),
            "recent_turns": [
                {"role": u.role, "text": u.text[-200:]}
                for u in self._working.get(sid, [])[-6:]
            ],
        }

        return Response(
            ts=event.ts,
            text="",
            data={"memory": memory_ctx},
        )

    async def handle_action(
        self, action_type: str, params: Dict, session_id: str = "default"
    ) -> Response:
        if action_type == "memory.write":
            key = params.get("key", "")
            value = params.get("value", "")
            self._do_write(session_id, key, value)
            return Response(
                ts=self._now_ms(),
                text="",
                debug={"memory": f"wrote {key}={value}"},
            )
        elif action_type == "memory.read":
            key = params.get("key", "")
            facts = self._get_all_facts(session_id)
            if key:
                result = {key: facts.get(key, "")}
            else:
                result = facts
            return Response(
                ts=self._now_ms(),
                text="",
                data={"memory_read": result},
            )
        elif action_type == "memory.forget":
            key = params.get("key", "")
            self._facts.get(session_id, {}).pop(key, None)
            return Response(
                ts=self._now_ms(),
                text="",
                debug={"memory": f"forgot {key}"},
            )
        else:
            return Response(
                ts=self._now_ms(),
                text="",
                debug={"memory": f"unknown action {action_type}"},
            )

    def _do_write(self, sid: str, key: str, value: str) -> None:
        if sid not in self._facts:
            self._facts[sid] = {}
        self._facts[sid][key] = value

    def _get_all_facts(self, sid: str) -> Dict[str, str]:
        return dict(self._facts.get(sid, {}))
