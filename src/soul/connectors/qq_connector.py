from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Dict, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from ..contracts.envelope import Envelope
from ..contracts.protocol import MessageType, PROTOCOL_VERSION
from ..contracts.events import Event, SourceInfo


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_id() -> str:
    return uuid.uuid4().hex


class QQConnector:
    """Bridge between NapCatQQ (OneBot v11) and Soul Core.

    Connects to NapCat's WebSocket, converts QQ messages to Soul Envelopes,
    routes them through the Core Router, and sends responses back to QQ.

    Fully independent — does not depend on persona, memory, or any specific node.
    Set ``enabled=False`` or omit ``--qq`` to run Soul without QQ.
    """

    def __init__(
        self,
        napcat_ws_url: str = "ws://127.0.0.1:3001",
        napcat_http_url: str = "http://127.0.0.1:3000",
        router: Any = None,
    ) -> None:
        self._ws_url = napcat_ws_url
        self._http_url = napcat_http_url
        self._router = router
        self._ws: Optional[ClientConnection] = None
        self._running = False
        self._pending: Dict[str, asyncio.Future] = {}

        # Optional callback: called when Soul sends a reply.
        # Signature: async (session_id: str, text: str, ts: int) -> None
        self.on_assistant_reply: Optional[Callable] = None

    # ---- public API ----------------------------------------------------

    async def connect(self) -> None:
        """Connect to NapCat and start the event loop."""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    print(f"[QQ] Connected to NapCat at {self._ws_url}")
                    await self._recv_loop(ws)
            except (OSError, websockets.ConnectionClosed) as e:
                print(f"[QQ] Disconnected: {e}")
            except Exception as e:
                print(f"[QQ] Error: {e}")

            if self._running:
                print("[QQ] Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def disconnect(self) -> None:
        """Gracefully disconnect."""
        self._running = False
        if self._ws:
            await self._ws.close()

    async def send_message(
        self, target_type: str, target_id: int, text: str, group_id: Optional[int] = None
    ) -> bool:
        """Send a message to QQ. Returns True on success.

        target_type: "private" or "group"
        target_id: user_id for private, group_id for group
        """
        if target_type == "private":
            return await self._call_api("send_private_msg", {
                "user_id": target_id,
                "message": text,
            })
        else:
            gid = group_id or target_id
            return await self._call_api("send_group_msg", {
                "group_id": gid,
                "message": text,
            })

    # ---- receive loop --------------------------------------------------

    async def _recv_loop(self, ws: ClientConnection) -> None:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Handle API response echoes
            if "echo" in data and data.get("echo") in self._pending:
                echo = data.pop("echo")
                future = self._pending.pop(echo, None)
                if future and not future.done():
                    future.set_result(data)
                continue

            # Handle events
            post_type = data.get("post_type", "")
            if post_type == "message":
                asyncio.create_task(self._on_message(data))

    # ---- message handler -----------------------------------------------

    async def _on_message(self, data: Dict) -> None:
        message_type = data.get("message_type", "private")
        user_id = data.get("user_id", 0)
        sender = data.get("sender", {})
        sender_name = sender.get("nickname", "") or sender.get("card", "") or str(user_id)
        raw_message = data.get("message", "")
        message_id = data.get("message_id", 0)

        # Extract plain text from OneBot message format
        text = self._extract_text(raw_message)

        # Build session id
        if message_type == "private":
            session_id = f"qq_private_{user_id}"
            scene = "private"
        else:
            group_id = data.get("group_id", 0)
            session_id = f"qq_group_{group_id}"
            scene = "group"

        # Build Soul Event
        event = Event(
            schema="soul.event/1",
            name="user.message",
            source=SourceInfo(
                kind="user",
                id=f"qq_{user_id}",
                display=sender_name,
            ),
            ts=_now_ms(),
            text=text,
            data={
                "qq_message_id": message_id,
                "qq_user_id": user_id,
                "qq_message_type": message_type,
                "scene": scene,
                "sender_name": sender_name,
            },
            tags={},
            priority=0,
        )

        if message_type == "group":
            event.data["group_id"] = data.get("group_id", 0)

        # Build envelope
        env = Envelope(
            v=PROTOCOL_VERSION,
            type=MessageType.event,
            id=_new_id(),
            ts=event.ts,
            session_id=session_id,
            trace=None,
            payload=event.model_dump(),
        )

        # Route through Core
        if self._router is None:
            return

        try:
            result_env = await self._router.route(env)
        except Exception as e:
            print(f"[QQ] Router error: {e}")
            return

        if result_env is None:
            return

        # Extract response payload
        if result_env.type == MessageType.response:
            resp_data = result_env.payload
            reply_text = resp_data.get("text", "") if isinstance(resp_data, dict) else ""
        else:
            return

        # Send reply if there's text
        if reply_text and reply_text.strip():
            target_id = user_id if message_type == "private" else data.get("group_id", 0)
            await self.send_message(message_type, target_id, reply_text.strip(),
                                    group_id=data.get("group_id"))

            # Notify that Soul replied (for memory storage)
            if self.on_assistant_reply:
                try:
                    await self.on_assistant_reply(session_id, reply_text.strip(), _now_ms())
                except Exception:
                    pass

    # ---- OneBot API call ------------------------------------------------

    async def _call_api(self, action: str, params: Dict) -> bool:
        """Call OneBot API via WebSocket or HTTP fallback."""
        # Try WebSocket first
        if self._ws:
            try:
                echo = _new_id()
                future: asyncio.Future = asyncio.get_event_loop().create_future()
                self._pending[echo] = future
                await self._ws.send(json.dumps({
                    "action": action,
                    "params": params,
                    "echo": echo,
                }, ensure_ascii=False))
                resp = await asyncio.wait_for(future, timeout=10)
                return resp.get("status") == "ok"
            except Exception:
                pass

        # HTTP fallback
        try:
            import requests
            r = requests.post(
                f"{self._http_url}/{action}",
                json=params,
                timeout=10,
            )
            return r.status_code == 200
        except Exception:
            return False

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _extract_text(raw_message: Any) -> str:
        """Extract plain text from OneBot v11 message format.

        Messages can be:
          - str: plain text
          - list: [{"type": "text", "data": {"text": "hello"}}, {"type": "image", ...}]
        """
        if isinstance(raw_message, str):
            return raw_message.strip()
        if isinstance(raw_message, list):
            parts = []
            for seg in raw_message:
                if isinstance(seg, dict) and seg.get("type") == "text":
                    parts.append(seg.get("data", {}).get("text", ""))
            return "".join(parts).strip()
        return str(raw_message).strip()
