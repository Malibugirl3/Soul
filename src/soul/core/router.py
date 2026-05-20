from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from ..contracts.envelope import Envelope
from ..contracts.events import Event
from ..contracts.protocol import MessageType, PROTOCOL_VERSION
from ..contracts.response import Response
from ..contracts.state import SoulState
from ..contracts.node import NodeIdentity, NodeRegistration
from ..contracts.capability import CapabilityManifest
from ..contracts.spark import SparkMessage, SparkVerb
from ..contracts.subscription import StateSubscription

from .state_aggregator import StateAggregator
from .node_registry import NodeRegistry
from .action_registry import ActionRegistry
from .event_bus import EventBus
from .pipeline import Pipeline
from .session_manager import SessionManager


class Router:
    """Central facade: dispatch Envelope by type to the appropriate subsystem.

    This replaces the old runtime/router.py. It coordinates all Core components.
    """

    def __init__(
        self,
        node_registry: Optional[NodeRegistry] = None,
        action_registry: Optional[ActionRegistry] = None,
        event_bus: Optional[EventBus] = None,
        state_aggregator: Optional[StateAggregator] = None,
        pipeline: Optional[Pipeline] = None,
    ) -> None:
        self.nodes = node_registry or NodeRegistry()
        self.actions = action_registry or ActionRegistry()
        self._state = state_aggregator or StateAggregator(SessionManager())
        self._pipeline = pipeline or Pipeline(
            node_registry=self.nodes,
            event_bus=None,
            state_aggregator=self._state,
        )
        self._bus = event_bus or EventBus()
        self._bus.wire(self._pipeline, self.nodes, self.actions, self._state)

    async def start(self) -> None:
        await self._bus.start()
        await self.nodes.start_monitor()

    async def stop(self) -> None:
        await self._bus.stop()
        await self.nodes.stop_monitor()

    async def route(
        self, env: Envelope, conn: Any = None
    ) -> Optional[Envelope]:
        handler = self._dispatch.get(env.type)
        if handler is None:
            return self._reply(
                env,
                Response(
                    ts=self._now_ms(),
                    text=f"unsupported type: {env.type.value}",
                ),
            )
        return await handler(env, conn)

    # ---- dispatchers ----

    async def _handle_event(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        event = Event.model_validate(env.payload)
        resp = await self._bus.submit(env)
        return self._reply(env, resp)

    async def _handle_heartbeat(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        return self._reply(env, Response(ts=self._now_ms(), text="pong"))

    async def _handle_register(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        reg = NodeRegistration.model_validate(env.payload)
        node_id = self.nodes.register(
            reg.identity, reg.capabilities, reg.subscriptions, conn
        )
        ack = {
            "schema_id": "soul.register_ack/1",
            "node_id": node_id,
            "session_id": env.session_id,
            "ts": self._now_ms(),
        }
        return self._reply(env, ack, msg_type=MessageType.register_ack)

    async def _handle_capability_announce(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        manifest = CapabilityManifest.model_validate(env.payload)
        self.actions.register_manifest(manifest)
        return None

    async def _handle_state_subscribe(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        sub = StateSubscription.model_validate(env.payload)
        await self._state.subscribe(sub)
        return None

    async def _handle_state_unsubscribe(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        data = env.payload
        node_id = data.get("node_id", "")
        await self._state.unsubscribe(node_id)
        return None

    async def _handle_spark(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        spark = SparkMessage.model_validate(env.payload)
        result = await self._bus.submit_spark(spark)
        if result:
            return self._reply(env, result)
        return None

    async def _handle_action_result(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        return None

    async def _handle_control(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        return self._reply(
            env,
            Response(
                ts=self._now_ms(), text="control received"
            ),
        )

    async def _handle_error(
        self, env: Envelope, conn: Any
    ) -> Optional[Envelope]:
        return None

    # ---- internal ----

    @property
    def _dispatch(self) -> dict:
        return {
            MessageType.event: self._handle_event,
            MessageType.heartbeat: self._handle_heartbeat,
            MessageType.register: self._handle_register,
            MessageType.capability_announce: self._handle_capability_announce,
            MessageType.state_subscribe: self._handle_state_subscribe,
            MessageType.state_unsubscribe: self._handle_state_unsubscribe,
            MessageType.spark: self._handle_spark,
            MessageType.action_result: self._handle_action_result,
            MessageType.control: self._handle_control,
            MessageType.error: self._handle_error,
        }

    def _reply(
        self,
        env: Envelope,
        payload: Any,
        msg_type: MessageType = MessageType.response,
    ) -> Envelope:
        if isinstance(payload, Response):
            payload_dict = payload.model_dump()
        elif hasattr(payload, "model_dump"):
            payload_dict = payload.model_dump()
        else:
            payload_dict = payload
        return Envelope(
            v=PROTOCOL_VERSION,
            type=msg_type,
            id=self._new_id(),
            ts=self._now_ms(),
            session_id=env.session_id,
            trace=env.trace,
            payload=payload_dict,
        )

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _new_id() -> str:
        import uuid
        return uuid.uuid4().hex
