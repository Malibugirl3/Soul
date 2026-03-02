from __future__ import annotations

import re
from typing import Tuple, Optional

from ..contracts.events import Event
from ..contracts.response import Response
from ..contracts.state import SoulState, Utterance
from ..contracts.protocol import EventName, MAX_WORKING_MEMORY

from .llm.ollama_client import OllamaClient

class SoulEngine:
    """
    Minimal engine:
    - updates dialog state
    - returns an echo response

    Futrue:
    - policy/memory/llm pipeline will live here (or be called from here)
    """
    def __init__(self):
        self.llm = OllamaClient()

    def handle_event(self, state: SoulState, event: Event) -> Tuple[SoulState, Response]:
        # 1) state transision: turn counter
        state.dialog.turn_index += 1

        # 2) record user text (short-term)
        if event.text:
            state.dialog.last_user_text = event.text
            state.dialog.working_memory.append(
                Utterance(role="user", text=event.text, ts=event.ts)
            )

        # 3) generate reply (placeholder logic)
        reply_text = self._compose_reply(state, event)

        # 4) record assistant text
        state.dialog.last_assistant_text = reply_text
        state.dialog.working_memory.append(
            Utterance(role="assistant", text=reply_text, ts=event.ts)
        )
        if len(state.dialog.working_memory) > MAX_WORKING_MEMORY:
            state.dialog.working_memory = state.dialog.working_memory[-MAX_WORKING_MEMORY:]

        # 5) output
        resp = Response(
            ts = event.ts,
            text = reply_text,
            debug = {
                "turn_index": state.dialog.turn_index,
                "mode": state.mode.name,
                "event_name": event.name.value,
            },
        )

        return state, resp


    def _upsert_fact(self, state, key: str, value: str) -> None:
        """
        Upsert the k:v into the facts
        """
        value = value.strip()
        if not value:
            return
        
        prefix = f"{key}"
        new_fact = f"{key}:{value}"

        facts = state.memory.facts
        for i, f in enumerate(facts):
            if isinstance(f, str) and f.startswith(prefix):
                facts[i] = new_fact
                return
        facts.append(new_fact)


    def _extract_fact_kv(self, text: str) -> Optional[Tuple[str, str]]:
        """
        Rule-based fact extraction (only category A: name/likes/dislikes).
        Return (key, value) or None.
        """
        t = text.strip()

        # 1) 名字：我叫X / 我是X（尽量克制：避免“我是学生”这类误判）
        m = re.match(r"^(我叫|我是)\s*([^\s，。！？]{1,12})\s*$", t)
        if m:
            name = m.group(2)
            # 一些简单过滤：避免把“学生/男生/人”当名字（你可后续扩展词表）
            if name in {"学生", "男生", "女生", "人", "AI", "机器人"}:
                return None
            return ("user_name", name)

        # 2) 喜好：我喜欢X
        m = re.match(r"^我喜欢\s*([^\n，。！？]{1,30})\s*$", t)
        if m:
            return ("user_like", m.group(1))

        # 3) 讨厌：我讨厌X
        m = re.match(r"^我讨厌\s*([^\n，。！？]{1,30})\s*$", t)
        if m:
            return ("user_dislike", m.group(1))

        return None
    
    def _maybe_store_fact(self, state, text: Optional[str]) -> None:
        """若文本包含可提取事实，则写入 state.memory.facts。"""
        if not text:
            return
        kv = self._extract_fact_kv(text)
        if not kv:
            return
        key, value = kv
        self._upsert_fact(state, key, value)

    def _get_fact(self, state, key: str) -> str | None:
        prefix = f"{key}:"
        for f in state.memory.facts:
            if isinstance(f, str) and f.startswith(prefix):
                return f[len(prefix):].strip() or None
            return None

    def _compose_reply(self, state: SoulState, event: Event) -> str:
        # if event.name == "user.message" and event.text:
        #     return f"(Soul) received: {event.text}"
        # return f"(Soul) received: {event.name}"
        if event.name == EventName.MODE_SET:
            new_mode = event.data.get("name", "idle")
            state.mode.name = new_mode
            state.mode.since_ts = event.ts
            return f"Mode switched to {new_mode}"
        
        if event.name == EventName.USER_MESSAGE and event.text:
            self._maybe_store_fact(state, event.text)
            prompt = event.text

            try:
                text = self.llm.generate(prompt)
            except Exception as e:
                # LLM 失败时降级，别让链路断
                return f"(Soul) LLM error: {e}"
            return text
            
        return f"(Soul) received event: {event.name.value}"