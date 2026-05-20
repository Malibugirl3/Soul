from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from ..contracts.events import Event
from ..contracts.response import Response, Action
from ..contracts.state import SoulState, Utterance
from ..contracts.protocol import MAX_WORKING_MEMORY
from ..contracts.node import NodeIdentity
from ..contracts.capability import ActionSchema

from .base import BaseNode


class MemoryNode(BaseNode):
    """Persistent memory node backed by SQLite.

    Stores every conversation turn and builds per-person profiles over time.
    Fully independent — works with any session_id regardless of source (QQ, WS, etc.).

    Tables:
      - utterances: all conversation turns, keyed by session_id
      - person_profile: what Soul knows about each conversation partner
    """

    def __init__(
        self,
        node_id: str = "memory-01",
        db_path: str = "data/memory.db",
        max_recent_utterances: int = 30,
        standalone: bool = False,
    ) -> None:
        identity = NodeIdentity(
            node_id=node_id,
            node_type="memory",
            display_name="Memory Node",
        )
        super().__init__(identity, standalone=standalone)
        self._db_path = Path(db_path)
        self.max_recent = max_recent_utterances
        self._db_lock = asyncio.Lock()
        self._init_db()

    # ---- database init -------------------------------------------------

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS utterances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    sender_name TEXT DEFAULT '',
                    text TEXT NOT NULL,
                    ts INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_utt_session
                    ON utterances(session_id, ts);

                CREATE TABLE IF NOT EXISTS person_profile (
                    session_id TEXT PRIMARY KEY,
                    display_name TEXT DEFAULT '',
                    known_facts TEXT DEFAULT '{}',
                    relationship TEXT DEFAULT '',
                    last_seen_ts INTEGER DEFAULT 0,
                    conversation_count INTEGER DEFAULT 0
                );
            """)
            conn.commit()
        finally:
            conn.close()

    # ---- async DB helpers ----------------------------------------------

    async def _db_run(self, sql: str, params=(), fetch: bool = False):
        async with self._db_lock:
            def _run():
                conn = sqlite3.connect(str(self._db_path))
                try:
                    cur = conn.execute(sql, params)
                    if fetch:
                        rows = cur.fetchall()
                        return rows
                    conn.commit()
                    return None
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    # ---- capability ----------------------------------------------------

    def _action_schemas(self) -> List[ActionSchema]:
        return [
            ActionSchema(
                action_type="memory.write",
                description="Store a fact about the current conversation partner. Params: key (str), value (str)",
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
                description="Read facts about the current conversation partner. Params: key (str, optional)",
                params_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                },
            ),
            ActionSchema(
                action_type="memory.forget",
                description="Forget a fact. Params: key (str)",
                params_schema={
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            ),
            ActionSchema(
                action_type="memory.update_relationship",
                description="Update how Soul perceives the relationship with this person. Params: relationship (str)",
                params_schema={
                    "type": "object",
                    "properties": {"relationship": {"type": "string"}},
                    "required": ["relationship"],
                },
            ),
        ]

    # ---- pipeline entry point ------------------------------------------

    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        sid = state.session_id if state else "default"

        # Store the user's utterance
        if event.text:
            sender = event.source.display or event.source.id or ""
            await self._store_utterance(sid, "user", sender, event.text, event.ts)

        # Ensure profile exists
        await self._ensure_profile(sid, sender)

        # Retrieve context for the prompt
        recent = await self._get_recent_utterances(sid, self.max_recent)
        profile = await self._get_profile(sid)

        return Response(
            ts=event.ts,
            text="",
            data={
                "memory": {
                    "recent_utterances": [
                        {"role": r["role"], "sender": r["sender_name"], "text": r["text"]}
                        for r in recent
                    ],
                    "person_profile": profile,
                }
            },
        )

    # ---- action handlers -----------------------------------------------

    async def handle_action(
        self, action_type: str, params: Dict, session_id: str = "default"
    ) -> Response:
        ts = int(time.time() * 1000)

        if action_type == "memory.write":
            key = params.get("key", "")
            value = params.get("value", "")
            await self._write_fact(session_id, key, value)
            return Response(ts=ts, text="", debug={"memory": f"wrote {key}={value}"})

        elif action_type == "memory.read":
            key = params.get("key", "")
            facts = await self._get_facts(session_id)
            result = {key: facts.get(key, "")} if key else facts
            return Response(ts=ts, text="", data={"memory_read": result})

        elif action_type == "memory.forget":
            key = params.get("key", "")
            await self._remove_fact(session_id, key)
            return Response(ts=ts, text="", debug={"memory": f"forgot {key}"})

        elif action_type == "memory.update_relationship":
            rel = params.get("relationship", "")
            await self._update_relationship(session_id, rel)
            return Response(ts=ts, text="", debug={"memory": f"relationship updated"})

        else:
            return Response(ts=ts, text="", debug={"memory": f"unknown action {action_type}"})

    # ---- store / retrieve utterances ----------------------------------

    async def _store_utterance(
        self, sid: str, role: str, sender_name: str, text: str, ts: int
    ) -> None:
        await self._db_run(
            "INSERT INTO utterances (session_id, role, sender_name, text, ts) VALUES (?,?,?,?,?)",
            (sid, role, sender_name, text, ts),
        )

    async def store_assistant_reply(self, sid: str, text: str, ts: int) -> None:
        """Store Soul's own reply — called externally after a response is sent."""
        await self._store_utterance(sid, "assistant", "Soul", text, ts)

    async def _get_recent_utterances(self, sid: str, limit: int) -> List[Dict]:
        rows = await self._db_run(
            "SELECT role, sender_name, text, ts FROM utterances "
            "WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
            (sid, limit),
            fetch=True,
        )
        if not rows:
            return []
        results = [
            {"role": r[0], "sender_name": r[1], "text": r[2], "ts": r[3]}
            for r in reversed(rows)
        ]
        return results

    # ---- person profile ------------------------------------------------

    async def _ensure_profile(self, sid: str, display_name: str = "") -> None:
        now = int(time.time() * 1000)
        await self._db_run(
            """INSERT INTO person_profile (session_id, display_name, last_seen_ts, conversation_count)
               VALUES (?, ?, ?, 1)
               ON CONFLICT(session_id) DO UPDATE SET
               display_name = CASE WHEN display_name = '' AND ? != '' THEN ? ELSE display_name END,
               last_seen_ts = ?,
               conversation_count = conversation_count + 1""",
            (sid, display_name, now, display_name, display_name, now),
        )

    async def _get_profile(self, sid: str) -> Dict:
        rows = await self._db_run(
            "SELECT display_name, known_facts, relationship, conversation_count "
            "FROM person_profile WHERE session_id = ?",
            (sid,),
            fetch=True,
        )
        if not rows:
            return {"display_name": "", "known_facts": {}, "relationship": "", "conversation_count": 0, "is_new": True}

        row = rows[0]
        try:
            facts = json.loads(row[1]) if row[1] else {}
        except (json.JSONDecodeError, TypeError):
            facts = {}

        return {
            "display_name": row[0] or "",
            "known_facts": facts,
            "relationship": row[2] or "",
            "conversation_count": row[3] or 0,
            "is_new": False,
        }

    async def _get_facts(self, sid: str) -> Dict[str, str]:
        profile = await self._get_profile(sid)
        return profile.get("known_facts", {})

    async def _write_fact(self, sid: str, key: str, value: str) -> None:
        profile = await self._get_profile(sid)
        facts = profile.get("known_facts", {})
        facts[key] = value
        await self._db_run(
            "UPDATE person_profile SET known_facts = ? WHERE session_id = ?",
            (json.dumps(facts, ensure_ascii=False), sid),
        )

    async def _remove_fact(self, sid: str, key: str) -> None:
        profile = await self._get_profile(sid)
        facts = profile.get("known_facts", {})
        facts.pop(key, None)
        await self._db_run(
            "UPDATE person_profile SET known_facts = ? WHERE session_id = ?",
            (json.dumps(facts, ensure_ascii=False), sid),
        )

    async def _update_relationship(self, sid: str, relationship: str) -> None:
        await self._db_run(
            "UPDATE person_profile SET relationship = ? WHERE session_id = ?",
            (relationship, sid),
        )

    # ---- formatted context for prompt ----------------------------------

    @staticmethod
    def format_person_profile(profile: Dict) -> str:
        """Format a person_profile dict into readable text for the prompt."""
        if profile.get("is_new"):
            return "你还不认识这个人，这是你们第一次聊天。"

        parts = []
        name = profile.get("display_name", "")
        if name:
            parts.append(f"- 名字：{name}")

        facts = profile.get("known_facts", {})
        if facts:
            fact_strs = []
            for k, v in facts.items():
                fact_strs.append(f"{k}：{v}")
            parts.append(f"- 你对TA的了解：{'，'.join(fact_strs)}")

        rel = profile.get("relationship", "")
        if rel:
            parts.append(f"- 你们的关系：{rel}")

        count = profile.get("conversation_count", 0)
        if count:
            parts.append(f"- 你们聊过 {count} 次")

        return "\n".join(parts) if parts else "你对这个人了解不多。"

    @staticmethod
    def format_recent_utterances(utterances: List[Dict]) -> str:
        """Format recent utterances into a readable conversation transcript."""
        if not utterances:
            return "(还没有对话记录)"

        lines = []
        for u in utterances:
            sender = u.get("sender_name", "") or u.get("role", "")
            text = u.get("text", "")
            lines.append(f"{sender}: {text}")
        return "\n".join(lines)
