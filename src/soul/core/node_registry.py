from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Set

from ..contracts.node import NodeIdentity, NodeRegistration, NodeStatus


class NodeInfo:
    def __init__(
        self,
        identity: NodeIdentity,
        capabilities: List[str],
        subscriptions: List[str],
        conn: Any = None,
    ) -> None:
        self.identity = identity
        self.capabilities = capabilities
        self.subscriptions = subscriptions
        self.conn = conn
        self.status = NodeStatus(
            node_id=identity.node_id,
            status="online",
            last_heartbeat_ts=self._now_ms(),
            uptime_ms=0,
        )
        self._start_ts = self._now_ms()

    def heartbeat(self) -> None:
        self.status.last_heartbeat_ts = self._now_ms()
        self.status.uptime_ms = self._now_ms() - self._start_ts
        if self.status.status == "stale":
            self.status.status = "online"

    def mark_stale(self) -> None:
        if self.status.status == "online":
            self.status.status = "stale"

    def mark_offline(self) -> None:
        self.status.status = "offline"

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)


class NodeRegistry:
    """Tracks connected nodes: registration, heartbeat, timeout detection."""

    def __init__(self) -> None:
        self._nodes: Dict[str, NodeInfo] = {}
        self._monitor_task: Optional[asyncio.Task] = None
        self._on_node_leave: List[callable] = []

    # ---- lifecycle ----

    def register(
        self,
        identity: NodeIdentity,
        capabilities: List[str],
        subscriptions: List[str],
        conn: Any = None,
    ) -> str:
        node_id = identity.node_id
        info = NodeInfo(identity, capabilities, subscriptions, conn)
        self._nodes[node_id] = info
        return node_id

    def unregister(self, node_id: str) -> bool:
        info = self._nodes.pop(node_id, None)
        if info:
            info.mark_offline()
            for cb in self._on_node_leave:
                cb(node_id, info.identity.node_type)
            return True
        return False

    def heartbeat(self, node_id: str) -> None:
        info = self._nodes.get(node_id)
        if info:
            info.heartbeat()

    # ---- query ----

    def get(self, node_id: str) -> Optional[NodeInfo]:
        return self._nodes.get(node_id)

    def get_by_type(self, node_type: str) -> List[NodeInfo]:
        return [
            n
            for n in self._nodes.values()
            if n.identity.node_type == node_type
            and n.status.status in ("online", "busy")
        ]

    def get_active(self) -> List[NodeInfo]:
        return [
            n
            for n in self._nodes.values()
            if n.status.status in ("online", "busy")
        ]

    def list_types(self) -> Set[str]:
        return {n.identity.node_type for n in self._nodes.values()}

    # ---- heartbeat monitor ----

    async def start_monitor(self, interval_ms: int = 5000) -> None:
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval_ms))

    async def stop_monitor(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            self._monitor_task = None

    async def _monitor_loop(self, interval_ms: int) -> None:
        while True:
            await asyncio.sleep(interval_ms / 1000)
            now = self._now_ms()
            stale = set()
            offline = set()
            for node_id, info in self._nodes.items():
                if info.status.status == "offline":
                    continue
                gap = now - info.status.last_heartbeat_ts
                if gap > 60000:  # 60s no heartbeat -> offline
                    offline.add(node_id)
                elif gap > 30000:  # 30s no heartbeat -> stale
                    stale.add(node_id)
            for node_id in stale:
                info = self._nodes.get(node_id)
                if info:
                    info.mark_stale()
            for node_id in offline:
                self.unregister(node_id)

    def on_node_leave(self, callback: callable) -> None:
        self._on_node_leave.append(callback)

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
