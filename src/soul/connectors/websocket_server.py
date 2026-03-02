from __future__ import annotations

import asyncio    # asyncio 事件循环与协程支持
import json
import time
import uuid
from typing import Any, Dict, Optional

import websockets   # 轻量 asyncio 实现
from websockets.asyncio.server import ServerConnection

from ..contracts.envelope import Envelope
from ..contracts.protocol import MessageType, PROTOCOL_VERSION
from ..runtime.engine import SoulEngine
from ..runtime.router import Router
from ..runtime.session_manager import SessionManager



def now_ms() -> int:
    return int(time.time() * 1000)

def new_id() -> str:
    return uuid.uuid4().hex


class WebSocketSoulServer:
    def __init__(self) -> None:
        self.sessions = SessionManager()
        self.router = Router(SoulEngine())

    # async def handler(self, ws, path: str) -> None:
    #     # Keep a simple path policy (optional)
    #     if path not in ("/ws", "/"):
    #         await ws.close(code=1008, reason="Invalid path")
    #         return 
        
    #     async for raw in ws:
    #         # 1) Parse and validate envelope
    #         try:
    #             data = json.loads(raw)
    #             env = Envelope.model_validate(data)
    #         except Exception as e:
    #             await ws.send(json.dumps(self._error_envelope(f"invalid envelope: {e}"), ensure_ascii = False))
    #             continue

    #         # 2) Load session state
    #         state = self.sessions.get_or_create(env.session_id)

    #         # 3) Route -> engine
    #         try:
    #             resp = self.router.route(state, env)
    #             self.sessions.set(state)
    #         except Exception as e:
    #             await ws.send(
    #                 json.dumps(
    #                     self._error_envelope(f"runtime error: {e}", session_id = env.session_id),
    #                     ensure_ascii = False,
    #                 )
    #             )
    #             continue

    #         # 4) Send response (if any)
    #         if resp is None:
    #             continue

    #         out_env = {
    #             "v": PROTOCOL_VERSION,   # 版本号
    #             "type": MessageType.response.value,
    #             "id": new_id(),
    #             "ts": now_ms(),
    #             "session_id": env.session_id,
    #             "trace": env.trace.model_dump() if env.trace else None,
    #             "payload": resp.model_dump(),
    #         }
    #         await ws.send(json.dumps(out_env, ensure_ascii=False))

    async def handler(self, conn: ServerConnection) -> None:
        # In websockers>=16. handler receives a ServerConnection (no 'path' argument).
        # Path can be inspected via conn request.path.
        
        # Path checking debug
        # path = getattr(getattr(conn, "request", None), "path", None)
        # if path not in("ws/", "/"):
        #     await conn.close(code=1008, reason="Invalid path")
        #     return
        
        async for raw in conn:
            # 1) Parse and validate envelope
            try:
                data = json.loads(raw)
                env = Envelope.model_validate(data)
            except Exception as e:
                await conn.send(json.dumps(self._error_envelope(f"invalid envelope: {e}"), ensure_ascii = False))
                continue

            # 2) Load session state
            state = self.sessions.get_or_create(env.session_id)

            #3) Route -> engine
            try:
                resp = self.router.route(state, env)
                self.sessions.set(state)
            except Exception as e:
                await conn.send(
                    json.dumps(
                        self._error_envelope(f"runtime error: {e}", session_id=env.session_id),
                        ensure_ascii = False,
                    )
                )
                continue

            # 4) Send response (if any)
            if resp is None:
                continue

            out_env = {
                "v": PROTOCOL_VERSION,
                "type": MessageType.response.value,
                "id": new_id(),
                "ts": now_ms(),
                "session_id": env.session_id,
                "trace": env.trace.model_dump() if env.trace else None,
                "payload": resp.model_dump(),
            }
            await conn.send(json.dumps(out_env, ensure_ascii=False))

    def _error_envelope(self, message: str, session_id: str = "unknown"):
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
    
async def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = WebSocketSoulServer()
    async with websockets.serve(server.handler, host, port):
        print(f"[Soul] WebSocket server listening on ws://{host}:{port}/ws")
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())