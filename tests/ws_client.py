import asyncio 
import json 
import time
import uuid

import websockets


def now_ms() -> int:
    return int(time.time() * 1000)


def mid() -> str:
    return uuid.uuid4().hex


async def main() -> None:
    uri = "ws://127.0.0.1:8765/ws"
    async with websockets.connect(uri) as ws:
        env = {  # 构造 envent Envelope
            "v": "1",
            "type": "event",
            "id": mid(),
            "ts": now_ms(),
            "session_id": "local:pet_1",
            "trace": {
                "trace_id": mid(), 
                "span_id": None, 
                "parent_span_id": None,
                "tags": {
                    "from": "client"
                },
            },
            "payload": {
                "schema_id": "soul.event/1",
                "name": "user.message",
                "source": {
                    "kind": "user",
                    "id": "u1",
                    "display": "tester",
                },
                "ts": now_ms(),
                "text": "你好",
                "data": {},
                "tags": {},
                "priority": 0,
                "ttl_ms": None,
                "idempotency_key": None,
            },
        }
        await ws.send(json.dumps(env, ensure_ascii=False))
        reply = await ws.recv()
        print("RECV:", reply)


asyncio.run(main())