from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from ..contracts.envelope import Envelope
from ..contracts.events import Event
from ..contracts.protocol import MessageType, UrgencyLevel, SparkVerb
from ..contracts.spark import SparkMessage
from ..contracts.response import Response


class EventBus:
    """Central event routing with priority queues and Spark protocol support.

    Three priority levels: immediate > soon > later.
    immediate events can preempt current processing.
    """

    def __init__(self) -> None:
        self._queues: Dict[UrgencyLevel, asyncio.Queue] = {
            UrgencyLevel.immediate: asyncio.Queue(),
            UrgencyLevel.soon: asyncio.Queue(),
            UrgencyLevel.later: asyncio.Queue(),
        }
        self._correlations: Dict[str, asyncio.Event] = {}
        self._correlation_results: Dict[str, SparkMessage] = {}
        self._running = False
        self._process_task: Optional[asyncio.Task] = None
        self._pipeline = None  # set by Router
        self._node_registry = None
        self._action_registry = None
        self._state_aggregator = None
        self._spark_handlers: Dict[str, callable] = {}

    def wire(
        self, pipeline, node_registry, action_registry, state_aggregator
    ) -> None:
        self._pipeline = pipeline
        self._node_registry = node_registry
        self._action_registry = action_registry
        self._state_aggregator = state_aggregator

    async def submit(
        self, envelope: Envelope, urgency: UrgencyLevel = UrgencyLevel.soon
    ) -> Response:
        event_id = envelope.id
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        item = (event_id, envelope, urgency, future)
        await self._queues[urgency].put(item)
        return await future

    async def submit_spark(self, spark_msg: SparkMessage) -> Optional[SparkMessage]:
        if spark_msg.verb == SparkVerb.notify:
            await self._route_spark(spark_msg)
            return None
        if spark_msg.verb == SparkVerb.emit:
            await self._broadcast_spark(spark_msg)
            return None
        if spark_msg.verb == SparkVerb.command:
            return await self._request_reply_spark(spark_msg)
        return None

    async def start(self) -> None:
        self._running = True
        self._process_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None

    def queue_depth(self) -> Dict[str, int]:
        return {
            "immediate": self._queues[UrgencyLevel.immediate].qsize(),
            "soon": self._queues[UrgencyLevel.soon].qsize(),
            "later": self._queues[UrgencyLevel.later].qsize(),
        }

    # ---- internals ----

    async def _process_loop(self) -> None:
        while self._running:
            item = await self._dequeue()
            if item is None:
                await asyncio.sleep(0.01)
                continue
            event_id, envelope, urgency, future = item
            try:
                if envelope.type == MessageType.spark:
                    spark = SparkMessage.model_validate(envelope.payload)
                    result = await self.submit_spark(spark)
                    future.set_result(
                        Response(ts=self._now_ms(), text="spark_ok")
                    )
                elif envelope.type == MessageType.event:
                    event = Event.model_validate(envelope.payload)
                    if self._pipeline is None:
                        future.set_result(
                            Response(
                                ts=self._now_ms(),
                                text="bus not wired to pipeline",
                                debug={"error": "pipeline not wired"},
                            )
                        )
                    else:
                        response = await self._pipeline.execute(
                            envelope.session_id, event, envelope
                        )
                        future.set_result(response)
                else:
                    future.set_result(
                        Response(
                            ts=self._now_ms(),
                            text=f"unhandled type on bus: {envelope.type.value}",
                        )
                    )
            except Exception as exc:
                future.set_result(
                    Response(
                        ts=self._now_ms(),
                        text=f"event bus error: {exc}",
                        debug={"error": str(exc)},
                    )
                )

    async def _dequeue(self):
        for level in (UrgencyLevel.immediate, UrgencyLevel.soon, UrgencyLevel.later):
            q = self._queues[level]
            if not q.empty():
                return await q.get()
        try:
            return await asyncio.wait_for(
                self._queues[UrgencyLevel.soon].get(), timeout=0.05
            )
        except asyncio.TimeoutError:
            try:
                return await asyncio.wait_for(
                    self._queues[UrgencyLevel.later].get(), timeout=0.05
                )
            except asyncio.TimeoutError:
                return await self._queues[UrgencyLevel.immediate].get()

    async def _route_spark(self, msg: SparkMessage) -> None:
        if msg.target_node:
            pass  # delivery handled by core router per node connection
        handler = self._spark_handlers.get(msg.action or "")
        if handler:
            await handler(msg)

    async def _broadcast_spark(self, msg: SparkMessage) -> None:
        pass  # delivery handled by core router per node connection

    async def _request_reply_spark(self, msg: SparkMessage) -> Optional[SparkMessage]:
        if not msg.correlation_id:
            return None
        evt = asyncio.Event()
        self._correlations[msg.correlation_id] = evt
        await self._route_spark(msg)
        try:
            await asyncio.wait_for(evt.wait(), timeout=(msg.ttl_ms or 10000) / 1000)
        except asyncio.TimeoutError:
            return None
        return self._correlation_results.pop(msg.correlation_id, None)

    def on_spark(self, action: str, handler: callable) -> None:
        self._spark_handlers[action] = handler

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
