from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, Optional

import websockets
from websockets.asyncio.server import ServerConnection

from ..contracts.envelope import Envelope
from ..contracts.protocol import MessageType, PROTOCOL_VERSION
from ..core.router import Router
from ..core.node_registry import NodeRegistry
from ..core.action_registry import ActionRegistry
from ..core.event_bus import EventBus
from ..core.state_aggregator import StateAggregator
from ..core.pipeline import Pipeline
from ..core.session_manager import SessionManager
from ..nodes.reasoning import ReasoningNode


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex


class WebSocketSoulServer:
    """Multi-connection WebSocket server.

    Handles two connection types:
      - Client: end-user sending events (traditional flow)
      - Node: internal node registering for pipeline participation

    First message determines connection type:
      type=register -> node connection
      anything else  -> client connection
    """

    def __init__(self, standalone: bool = False) -> None:
        self.standalone = standalone
        self._sm = SessionManager()
        self._state = StateAggregator(self._sm)
        self._nodes = NodeRegistry()
        self._actions = ActionRegistry()
        self._bus = EventBus()
        self._pipeline = Pipeline(
            node_registry=self._nodes,
            event_bus=self._bus,
            state_aggregator=self._state,
        )
        self.router = Router(
            node_registry=self._nodes,
            action_registry=self._actions,
            event_bus=self._bus,
            state_aggregator=self._state,
            pipeline=self._pipeline,
        )
        # Track node WS connections for event forwarding
        self._node_connections: Dict[str, ServerConnection] = {}

        # Standalone: wire in-process nodes
        if standalone:
            self._reasoning = ReasoningNode(
                node_id="reasoning-01", standalone=True
            )
            self._reasoning.set_action_registry(self._actions)
            self._pipeline.set_forward_handler(
                "reasoning", self._reasoning.forward_handler
            )

    async def start(self) -> None:
        await self.router.start()
        self._nodes.on_node_leave(self._on_node_disconnect)

    async def handler(self, conn: ServerConnection) -> None:
        first = True
        is_node_conn = False
        node_id: Optional[str] = None

        async for raw in conn:
            try:
                data = json.loads(raw)
                env = Envelope.model_validate(data)
            except Exception as e:
                await conn.send(
                    json.dumps(
                        self._error_envelope(f"invalid envelope: {e}"),
                        ensure_ascii=False,
                    )
                )
                continue

            # Detect connection type from first message
            if first:
                first = False
                if env.type == MessageType.register:
                    is_node_conn = True
                    # Handle registration inline so we get node_id
                    result = await self.router.route(env, conn)
                    if result and result.type == MessageType.register_ack:
                        node_id = result.payload.get("node_id", "")
                        self._node_connections[node_id] = conn
                        # Wire Pipeline forward handler for this node type
                        info = self._nodes.get(node_id)
                        if info:
                            self._pipeline.set_forward_handler(
                                info.identity.node_type,
                                self._make_node_forwarder(node_id),
                            )
                    if result:
                        await conn.send(
                            json.dumps(
                                self._serialize_envelope(result),
                                ensure_ascii=False,
                            )
                        )
                    continue

            if is_node_conn:
                # Forward node messages to the router
                result = await self.router.route(env, conn)
                if result:
                    await conn.send(
                        json.dumps(
                            self._serialize_envelope(result),
                            ensure_ascii=False,
                        )
                    )
            else:
                # Client connection: standard event flow
                try:
                    result = await self.router.route(env, conn)
                    if result:
                        await conn.send(
                            json.dumps(
                                self._serialize_envelope(result),
                                ensure_ascii=False,
                            )
                        )
                except Exception as e:
                    await conn.send(
                        json.dumps(
                            self._error_envelope(
                                f"runtime error: {e}",
                                session_id=env.session_id,
                            ),
                            ensure_ascii=False,
                        )
                    )

    def _make_node_forwarder(self, node_id: str):
        """Create a forward handler that sends event_forward to a node over WS."""

        async def forward(event, envelope, step_type, context):
            node_conn = self._node_connections.get(node_id)
            if not node_conn:
                return None
            enriched_event_data = event.model_dump()
            enriched_event_data["data"] = context
            fwd = Envelope(
                v=PROTOCOL_VERSION,
                type=MessageType.event_forward,
                id=new_id(),
                ts=now_ms(),
                session_id=envelope.session_id,
                trace=envelope.trace,
                payload=enriched_event_data,
            )
            await node_conn.send(
                json.dumps(self._serialize_envelope(fwd), ensure_ascii=False)
            )
            # Wait for response — in real networked mode this would be
            # async, but for now return a placeholder
            return None

        return forward

    def _on_node_disconnect(self, node_id: str, node_type: str) -> None:
        self._node_connections.pop(node_id, None)

    def _error_envelope(
        self, message: str, session_id: str = "unknown"
    ) -> dict:
        return {
            "v": PROTOCOL_VERSION,
            "type": MessageType.error.value,
            "id": new_id(),
            "ts": now_ms(),
            "session_id": session_id,
            "trace": None,
            "payload": {
                "schema_id": "soul.error/1",
                "code": "invalid_payload",
                "message": message,
                "details": None,
            },
        }

    @staticmethod
    def _serialize_envelope(env: Envelope) -> dict:
        return json.loads(env.model_dump_json())


async def main(
    host: str = "127.0.0.1", port: int = 8765, standalone: bool = False
) -> None:
    server = WebSocketSoulServer(standalone=standalone)
    await server.start()
    mode = "standalone" if standalone else "networked"
    async with websockets.serve(server.handler, host, port):
        print(
            f"[Soul v0.2] WebSocket server on ws://{host}:{port}/ws ({mode} mode)"
        )
        await asyncio.Future()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--standalone", action="store_true", help="Run all nodes in-process"
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Bind host"
    )
    parser.add_argument("--port", type=int, default=8765, help="Bind port")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use old runtime engine (v0.1 compat)",
    )
    args = parser.parse_args()

    if args.legacy:
        from ..runtime.engine import SoulEngine as OldEngine
        from ..runtime.router import Router as OldRouter
        from ..runtime.session_manager import SessionManager as OldSM

        async def legacy_main():
            sm = OldSM()
            router = OldRouter(OldEngine())

            async def legacy_handler(conn: ServerConnection) -> None:
                async for raw in conn:
                    try:
                        data = json.loads(raw)
                        env = Envelope.model_validate(data)
                    except Exception as e:
                        await conn.send(
                            json.dumps(
                                {
                                    "v": PROTOCOL_VERSION,
                                    "type": MessageType.error.value,
                                    "id": new_id(),
                                    "ts": now_ms(),
                                    "session_id": "unknown",
                                    "trace": None,
                                    "payload": {
                                        "schema_id": "soul.error/1",
                                        "code": "invalid_payload",
                                        "message": f"invalid envelope: {e}",
                                    },
                                },
                                ensure_ascii=False,
                            )
                        )
                        continue
                    state = sm.get_or_create(env.session_id)
                    try:
                        resp = router.route(state, env)
                        sm.set(state)
                    except Exception as e:
                        await conn.send(
                            json.dumps(
                                {
                                    "v": PROTOCOL_VERSION,
                                    "type": MessageType.error.value,
                                    "id": new_id(),
                                    "ts": now_ms(),
                                    "session_id": env.session_id,
                                    "trace": None,
                                    "payload": {
                                        "schema_id": "soul.error/1",
                                        "code": "runtime_error",
                                        "message": f"runtime error: {e}",
                                    },
                                },
                                ensure_ascii=False,
                            )
                        )
                        continue
                    if resp is None:
                        continue
                    out_env = {
                        "v": PROTOCOL_VERSION,
                        "type": MessageType.response.value,
                        "id": new_id(),
                        "ts": now_ms(),
                        "session_id": env.session_id,
                        "trace": (
                            env.trace.model_dump() if env.trace else None
                        ),
                        "payload": resp.model_dump(),
                    }
                    await conn.send(
                        json.dumps(out_env, ensure_ascii=False)
                    )

            async with websockets.serve(
                legacy_handler, args.host, args.port
            ):
                print(
                    f"[Soul v0.1] Legacy server on ws://{args.host}:{args.port}/ws"
                )
                await asyncio.Future()

        asyncio.run(legacy_main())
    else:
        asyncio.run(main(args.host, args.port, args.standalone))
