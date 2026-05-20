from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from ..contracts.envelope import Envelope, TraceContext
from ..contracts.protocol import MessageType, PROTOCOL_VERSION
from ..contracts.events import Event, SourceInfo
from ..contracts.response import Response
from ..contracts.state import SoulState
from ..contracts.node import NodeIdentity, NodeRegistration
from ..contracts.capability import ActionSchema, CapabilityManifest


class BaseNode(ABC):
    """Base for all federated nodes.

    Handles WebSocket connection to Core, registration, heartbeat,
    capability announcement, and reconnection. Subclasses override
    handle_event().
    """

    def __init__(
        self,
        identity: NodeIdentity,
        core_uri: str = "ws://127.0.0.1:8765/ws",
        standalone: bool = False,
    ) -> None:
        self.identity = identity
        self.core_uri = core_uri
        self.standalone = standalone
        self._ws: Optional[ClientConnection] = None
        self._running = False
        self._outbox: asyncio.Queue[Envelope] = asyncio.Queue()

    # ---- public API ----

    async def start(self) -> None:
        self._running = True
        if self.standalone:
            return  # No WS connection needed; called directly via forward handler
        await self._connect_loop()

    async def stop(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    @abstractmethod
    async def handle_event(
        self, event: Event, state: Optional[SoulState] = None
    ) -> Response:
        ...

    def get_capability_manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            node_id=self.identity.node_id,
            actions=self._action_schemas(),
            ts=self._now_ms(),
        )

    def _action_schemas(self) -> List[ActionSchema]:
        """Override to declare capabilities."""
        return []

    # ---- forward handler (standalone mode) ----

    async def forward_handler(
        self,
        event: Event,
        envelope: Envelope,
        step_type: str,
        context: Dict[str, Any],
    ) -> Response:
        """Called by Pipeline in standalone mode."""
        enriched_event = event.model_copy(update={"data": context})
        return await self.handle_event(enriched_event)

    # ---- WS client (networked mode) ----

    async def _connect_loop(self) -> None:
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(self.core_uri) as ws:
                    self._ws = ws
                    backoff = 1
                    await self._register(ws)
                    await asyncio.gather(
                        self._send_loop(ws),
                        self._recv_loop(ws),
                    )
            except Exception:
                if not self._running:
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _register(self, ws: ClientConnection) -> None:
        reg = NodeRegistration(
            identity=self.identity,
            capabilities=[a.action_type for a in self._action_schemas()],
            subscriptions=[],
        )
        env = Envelope(
            type=MessageType.register,
            id=self._new_id(),
            ts=self._now_ms(),
            session_id="node",
            payload=reg.model_dump(),
        )
        await ws.send(env.model_dump_json())
        # Send capability manifest
        manifest = self.get_capability_manifest()
        cap_env = Envelope(
            type=MessageType.capability_announce,
            id=self._new_id(),
            ts=self._now_ms(),
            session_id="node",
            payload=manifest.model_dump(),
        )
        await ws.send(cap_env.model_dump_json())

    async def _send_loop(self, ws: ClientConnection) -> None:
        while self._running:
            env = await self._outbox.get()
            if ws is None:
                continue
            try:
                await ws.send(env.model_dump_json())
            except Exception:
                await self._outbox.put(env)
                raise

    async def _recv_loop(self, ws: ClientConnection) -> None:
        async for raw in ws:
            try:
                data = json.loads(raw)
                env = Envelope.model_validate(data)
                await self._dispatch(ws, env)
            except Exception:
                continue

    async def _dispatch(
        self, ws: ClientConnection, env: Envelope
    ) -> None:
        if env.type == MessageType.event_forward:
            event = Event.model_validate(env.payload)
            resp = await self.handle_event(event)
            out = Envelope(
                type=MessageType.response,
                id=self._new_id(),
                ts=self._now_ms(),
                session_id=env.session_id,
                trace=env.trace,
                payload=resp.model_dump(),
            )
            await self._outbox.put(out)
        elif env.type == MessageType.heartbeat:
            hb = Envelope(
                type=MessageType.heartbeat,
                id=self._new_id(),
                ts=self._now_ms(),
                session_id=env.session_id,
                payload={"kind": "pong"},
            )
            await self._outbox.put(hb)
        elif env.type == MessageType.action_request:
            action_type = env.payload.get("type", "")
            params = env.payload.get("params", {})
            resp = Response(ts=self._now_ms(), text=f"action {action_type} done")
            out = Envelope(
                type=MessageType.action_result,
                id=self._new_id(),
                ts=self._now_ms(),
                session_id=env.session_id,
                trace=env.trace,
                payload=resp.model_dump(),
            )
            await self._outbox.put(out)

    # ---- helpers ----

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _new_id() -> str:
        import uuid
        return uuid.uuid4().hex
