from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from ..contracts.events import Event
from ..contracts.response import Response, Action
from ..contracts.state import SoulState
from ..contracts.protocol import EventName
from ..contracts.capability import ActionSchema
from ..contracts.personality import SoulPersona

from .base import BaseNode
from .memory import MemoryNode
from ..runtime.llm.ollama_client import OllamaClient


class ReasoningNode(BaseNode):
    """LLM-powered decision node with persona-driven conversation.

    Builds a role-playing prompt from SoulPersona + memory context,
    then calls the LLM to produce a natural response + optional actions.
    """

    def __init__(
        self,
        node_id: str = "reasoning-01",
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        persona: Optional[SoulPersona] = None,
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
        self._persona = persona or SoulPersona()
        self._action_registry = action_registry

    def set_persona(self, persona: SoulPersona) -> None:
        self._persona = persona

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
                text="",
                debug={"error": str(e)},
            )

        return self._parse_output(event.ts, llm_output)

    # ---- prompt building -----------------------------------------------

    def _build_prompt(self, event: Event) -> str:
        parts: List[str] = []
        context = event.data

        # 1. Persona — WHO Soul is (not WHAT to do)
        parts.append(self._persona.to_system_prompt())

        # 2. Scene context (group vs private)
        scene = context.get("scene", "private")
        if scene == "group":
            sender_name = context.get("sender_name", event.source.display or "someone")
            parts.append(
                f"\n你现在在一个 QQ 群里。大家正在聊天。刚才说话的人是 {sender_name}。\n"
                "除非有人直接跟你说话，或者你真的有话想说，再回复。保持自然即可。"
            )

        # 3. Perception — time / environment context
        perception = context.get("perception")
        if perception and isinstance(perception, dict):
            time_of_day = perception.get("time_of_day", "")
            if time_of_day:
                parts.append(f"\n现在是{time_of_day}。")

        # 4. Memory — who Soul is talking to + recent conversation
        memory = context.get("memory")
        if memory and isinstance(memory, dict):
            profile = memory.get("person_profile")
            recent = memory.get("recent_utterations")

            if profile:
                profile_text = MemoryNode.format_person_profile(profile)
                parts.append(f"\n关于你正在对话的对象：\n{profile_text}")

            if recent:
                recent_text = MemoryNode.format_recent_utterances(recent)
                parts.append(f"\n最近的对话记录：\n{recent_text}")

        # 5. Available actions (for memory.write, etc.)
        if self._action_registry:
            catalogue = self._action_registry.get_tool_catalogue()
            if catalogue:
                parts.append(f"\n你可以在回复中使用以下内部功能：\n{catalogue}\n")
                parts.append(
                    "使用方式：在回复末尾添加 ACTION: {\"type\": \"<功能>\", \"params\": {...}}"
                )

        # 6. Natural conversation reminder (gentle, not rules)
        parts.append(
            f"\n现在，请以 {self._persona.name} 的身份自然地回复。记住你是在跟人聊天：\n"
            "- 可以反问、可以分享自己的看法、可以说不知道\n"
            "- 回复简短自然，不要长篇大论\n"
            "- 用自己的说话方式，不要模仿对方\n"
        )

        # 7. Current message
        sender = event.source.display or "User"
        parts.append(f"\n{sender}: {event.text}")

        return "\n".join(parts)

    # ---- output parsing ------------------------------------------------

    def _parse_output(self, ts: int, llm_output: str) -> Response:
        text = llm_output.strip()
        actions: List[Action] = []

        # Extract ACTION blocks
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

        # Check for structured JSON output
        if not actions and llm_output.strip().startswith("{"):
            try:
                data = json.loads(llm_output)
                text = data.get("text", text)
                for a in data.get("actions", []):
                    actions.append(
                        Action(type=a.get("type", ""), params=a.get("params", {}))
                    )
            except json.JSONDecodeError:
                pass

        # Always add a text.send action so ActionNode routes the reply
        if text and text != "(no response)":
            actions.insert(0, Action(type="text.send", params={"text": text}))

        return Response(ts=ts, text=text, actions=actions)
