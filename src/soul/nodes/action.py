from __future__ import annotations

from typing import Dict, List, Optional

from ..contracts.events import Event
from ..contracts.response import Response, Action
from ..contracts.state import SoulState, StatePatch
from ..contracts.node import NodeIdentity
from ..contracts.capability import ActionSchema

from .base import BaseNode


class ActionNode(BaseNode):
    """Executes actions decided by the ReasoningNode.

    Registered actions: text.send, state.set, state.patch.
    Future: web.search, game.control, sound.play, etc.
    """

    def __init__(
        self,
        node_id: str = "action-01",
        standalone: bool = False,
    ) -> None:
        identity = NodeIdentity(
            node_id=node_id,
            node_type="action",
            display_name="Action Node",
        )
        super().__init__(identity, standalone=standalone)
        self._executed_actions: List[Dict] = []

    def _action_schemas(self) -> List[ActionSchema]:
        return [
            ActionSchema(
                action_type="text.send",
                description="Send a text response to the user",
                params_schema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The text to send",
                        },
                    },
                    "required": ["text"],
                },
            ),
            ActionSchema(
                action_type="state.set",
                description="Set a state variable (dot-path)",
                params_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "value": {},
                    },
                    "required": ["path", "value"],
                },
            ),
            ActionSchema(
                action_type="state.patch",
                description="Apply a batch of state changes",
                params_schema={
                    "type": "object",
                    "properties": {
                        "set": {"type": "object"},
                        "unset": {"type": "array", "items": {"type": "string"}},
                        "inc": {"type": "object"},
                    },
                },
            ),
        ]

    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        # Collect actions from the event context (placed by prior pipeline steps)
        pending: List[Action] = []

        # Extract actions embedded in the event data
        context = event.data
        if "_pending_actions" in context:
            pending.extend(context["_pending_actions"])

        # Also check for text that embeds actions
        if context.get("_prior_texts"):
            for t in context["_prior_texts"]:
                if isinstance(t, str) and "ACTION:" in t:
                    import json, re
                    for match in re.finditer(
                        r'ACTION:\s*(\{[^}]+\})', t
                    ):
                        try:
                            action_data = json.loads(match.group(1))
                            pending.append(
                                Action(
                                    type=action_data.get("type", ""),
                                    params=action_data.get("params", {}),
                                )
                            )
                        except json.JSONDecodeError:
                            pass

        results = []
        state_patches: Dict[str, dict] = {}
        final_text = ""

        for action in pending:
            result = self._execute(action)
            if result:
                results.append(result)
                if result.get("type") == "text.send":
                    final_text = result.get("text", "")
                if result.get("patch"):
                    state_patches.update(result["patch"])

        patch = None
        if state_patches:
            patch = StatePatch(set=state_patches)

        return Response(
            ts=event.ts,
            text=final_text,
            actions=pending,
            state_patch=patch,
            debug={"executed": results} if results else None,
        )

    def _execute(self, action: Action) -> Optional[Dict]:
        atype = action.type
        if atype == "text.send":
            text = action.params.get("text", "")
            self._executed_actions.append({"type": "text.send", "text": text})
            return {"type": "text.send", "text": text}
        elif atype == "state.set":
            path = action.params.get("path", "")
            value = action.params.get("value")
            return {"type": "state.set", "patch": {path: value}}
        elif atype == "state.patch":
            return {"type": "state.patch", "patch": action.params.get("set", {})}
        else:
            self._executed_actions.append(
                {"type": atype, "params": action.params}
            )
            return {"type": atype, "status": "acknowledged"}
