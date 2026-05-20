from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from ..contracts.state import SoulState, StatePatch
from ..contracts.subscription import StateChangeNotification, StateSubscription


class StateAggregator:
    """Single authoritative holder of SoulState per session.

    All state mutation flows through apply_patch(). Nodes receive
    StateChangeNotification when subscribed paths are touched.
    """

    def __init__(self, session_manager) -> None:
        self._sm = session_manager
        self._lock_per_session: Dict[str, asyncio.Lock] = {}
        self._subscribers: Dict[str, List[StateSubscription]] = {}

    # ---- session state ----

    def get_state(self, session_id: str) -> SoulState:
        return self._sm.get_or_create(session_id)

    async def apply_patch(
        self, session_id: str, patch: StatePatch, node_id: str = ""
    ) -> SoulState:
        lock = self._lock(session_id)
        async with lock:
            state = self._sm.get_or_create(session_id)
            self._do_apply(state, patch)
            state.state_version += 1
            self._sm.set(state)
            await self._notify(session_id, [patch])
            return state

    # ---- subscription ----

    async def subscribe(self, sub: StateSubscription) -> None:
        self._subscribers.setdefault(sub.node_id, []).append(sub)

    async def unsubscribe(self, node_id: str) -> None:
        self._subscribers.pop(node_id, None)

    # ---- internals ----

    def _lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._lock_per_session:
            self._lock_per_session[session_id] = asyncio.Lock()
        return self._lock_per_session[session_id]

    def _do_apply(self, state: SoulState, patch: StatePatch) -> None:
        for path, value in patch.set.items():
            self._set_path(state, path, value)
        for path in patch.unset:
            self._unset_path(state, path)
        for path, delta in patch.inc.items():
            current = self._get_path(state, path)
            if not isinstance(current, (int, float)):
                continue
            self._set_path(state, path, current + delta)

    async def _notify(
        self, session_id: str, patches: List[StatePatch]
    ) -> None:
        for node_id, subs in list(self._subscribers.items()):
            for sub in subs:
                if self._any_path_match(sub.paths, patches):
                    state = self._sm.get_or_create(session_id)
                    notification = StateChangeNotification(
                        session_id=session_id,
                        state_version=state.state_version,
                        patches=patches,
                        full_snapshot=None,
                        ts=self._now_ms(),
                    )
                    # fire-and-forget — subscribers handle delivery
                    asyncio.create_task(self._deliver(node_id, notification))

    async def _deliver(
        self, node_id: str, notification: StateChangeNotification
    ) -> None:
        # In standalone mode, the event_bus handles delivery.
        # In networked mode, the WS connection is used.
        # This is a hook point — override in subclass or wire via callback.
        pass

    @staticmethod
    def _any_path_match(paths: List[str], patches: List[StatePatch]) -> bool:
        for path in paths:
            for patch in patches:
                for p in patch.set:
                    if p.startswith(path.rstrip("*")):
                        return True
                for p in patch.unset:
                    if p.startswith(path.rstrip("*")):
                        return True
        return False

    @staticmethod
    def _get_path(state: SoulState, path: str) -> Any:
        parts = path.split(".")
        obj = state
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            elif hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                return None
        return obj

    @staticmethod
    def _set_path(state: SoulState, path: str, value: Any) -> None:
        parts = path.split(".")
        obj = state
        for p in parts[:-1]:
            if isinstance(obj, dict):
                obj = obj.setdefault(p, {})
            elif hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                return
        last = parts[-1]
        if isinstance(obj, dict):
            obj[last] = value
        elif hasattr(obj, last):
            setattr(obj, last, value)

    @staticmethod
    def _unset_path(state: SoulState, path: str) -> None:
        parts = path.split(".")
        obj = state
        for p in parts[:-1]:
            if isinstance(obj, dict):
                obj = obj.get(p)
            elif hasattr(obj, p):
                obj = getattr(obj, p)
            else:
                return
            if obj is None:
                return
        last = parts[-1]
        if isinstance(obj, dict):
            obj.pop(last, None)
        elif hasattr(obj, last):
            try:
                setattr(obj, last, None)
            except (AttributeError, ValueError):
                pass

    @staticmethod
    def _now_ms() -> int:
        import time
        return int(time.time() * 1000)
