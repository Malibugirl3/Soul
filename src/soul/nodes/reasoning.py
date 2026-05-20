from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ..contracts.events import Event, SourceInfo
from ..contracts.response import Response, Action
from ..contracts.state import SoulState, Utterance
from ..contracts.protocol import EventName, MAX_WORKING_MEMORY
from ..contracts.capability import ActionSchema

from .base import BaseNode
from ..runtime.llm.ollama_client import OllamaClient


class ReasoningNode(BaseNode):
    """LLM-powered decision node. Extracted from the old SoulEngine.

    Receives enriched events (with perception + memory context),
    calls the LLM to decide what to say and what actions to invoke.
    """

    def __init__(
        self,
        node_id: str = "reasoning-01",
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        action_registry=None,
        standalone: bool = False,
    ) -> None:
        from ..contracts.node import NodeIdentity

        identity = NodeIdentity(
            node_id=node_id,
            node_type="reasoning",
            display_name="Reasoning Node",
        )
        super().__init__(identity, standalone=standalone)
        self.llm = OllamaClient(model=model)
        self.llm.base_url = base_url
        self._action_registry = action_registry

    def set_action_registry(self, registry) -> None:
        self._action_registry = registry

    def _action_schemas(self) -> List[ActionSchema]:
        return [
            ActionSchema(
                action_type="reasoning.decide",
                description="Decide what to say and which actions to invoke based on the current context",
                params_schema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "The text to say"},
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "params": {"type": "object"},
                                },
                            },
                        },
                    },
                    "required": ["text"],
                },
            )
        ]

    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        if not event.text:
            return Response(ts=event.ts, text="", actions=[])

        prompt = self._build_prompt(event)
        try:
            llm_output = self.llm.generate(prompt)
        except Exception as e:
            return Response(
                ts=event.ts,
                text=f"(Reasoning) LLM error: {e}",
                debug={"error": str(e)},
            )

        return self._parse_output(event.ts, llm_output)

    def _build_prompt(self, event: Event) -> str:
        parts = []

        # System prompt
        parts.append(
            "You are a friendly AI assistant. You receive context from other modules "
            "and should respond naturally. You can also invoke actions when needed."
        )

        # Tool catalogue from ActionRegistry
        if self._action_registry:
            catalogue = self._action_registry.get_tool_catalogue()
            if catalogue:
                parts.append(f"\n{catalogue}\n")
                parts.append(
                    "When you need to use an action, include an ACTION block:\n"
                    'ACTION: {"type": "<action_type>", "params": {...}}\n'
                )

        # Context from prior pipeline steps
        context = event.data
        if context.get("perception"):
            parts.append(f"\n[Perception] {json.dumps(context['perception'], ensure_ascii=False)}")
        if context.get("memory"):
            parts.append(f"\n[Memory] {json.dumps(context['memory'], ensure_ascii=False)}")
        if context.get("_prior_texts"):
            parts.append(f"\n[Prior] {' | '.join(context['_prior_texts'])}")

        # User message
        parts.append(f"\nUser: {event.text}\nAssistant:")

        return "\n".join(parts)

    def _parse_output(self, ts: int, llm_output: str) -> Response:
        text = llm_output.strip()
        actions: List[Action] = []

        # Extract ACTION blocks from the output
        action_pattern = r'ACTION:\s*(\{[^}]+\})'
        for match in re.finditer(action_pattern, text):
            try:
                action_data = json.loads(match.group(1))
                actions.append(
                    Action(
                        type=action_data.get("type", "unknown"),
                        params=action_data.get("params", {}),
                    )
                )
            except json.JSONDecodeError:
                pass
            text = text.replace(match.group(0), "").strip()

        # If the whole output is valid JSON, parse it as structured output
        if not actions and llm_output.strip().startswith("{"):
            try:
                data = json.loads(llm_output)
                text = data.get("text", llm_output)
                for a in data.get("actions", []):
                    actions.append(
                        Action(type=a.get("type", ""), params=a.get("params", {}))
                    )
            except json.JSONDecodeError:
                pass

        if not text:
            text = "(no response)"

        return Response(ts=ts, text=text, actions=actions)
