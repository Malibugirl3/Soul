from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

from ..contracts.envelope import Envelope
from ..contracts.events import Event
from ..contracts.protocol import MessageType
from ..contracts.response import Response, Action
from ..contracts.state import StatePatch


DEFAULT_PIPELINE = ["perception", "memory", "reasoning", "action"]
STEP_TIMEOUT_MS = 10000


class Pipeline:
    """Configurable processing chain for events.

    Each step dispatches to a node type. Step output enriches the event
    context for subsequent steps. Failed steps are skipped (never crash).
    """

    def __init__(
        self,
        steps: Optional[List[str]] = None,
        node_registry=None,
        event_bus=None,
        state_aggregator=None,
        step_timeout_ms: int = STEP_TIMEOUT_MS,
        skip_on_error: bool = True,
    ) -> None:
        self.steps = steps or DEFAULT_PIPELINE
        self._registry = node_registry
        self._bus = event_bus
        self._state = state_aggregator
        self._step_timeout_ms = step_timeout_ms
        self._skip_on_error = skip_on_error
        self._forward_handlers: Dict[str, callable] = {}

    def set_forward_handler(self, node_type: str, handler: callable) -> None:
        self._forward_handlers[node_type] = handler

    async def execute(
        self, session_id: str, event: Event, envelope: Envelope
    ) -> Response:
        merged_actions: List[Action] = []
        merged_patches: Dict[str, Any] = {}
        unset_paths: List[str] = []
        inc_deltas: Dict[str, float] = {}
        debug_log: List[Dict[str, Any]] = []
        context: Dict[str, Any] = dict(event.data)

        for step_type in self.steps:
            start = time.time()
            try:
                step_resp = await self._dispatch_step(
                    session_id, event, envelope, step_type, context
                )
                elapsed_ms = int((time.time() - start) * 1000)
                if step_resp:
                    context.update(step_resp.data or {})
                    if step_resp.text:
                        context.setdefault("_prior_texts", []).append(
                            step_resp.text
                        )
                    merged_actions.extend(step_resp.actions)
                    if step_resp.state_patch:
                        for k, v in step_resp.state_patch.set.items():
                            merged_patches[k] = v
                        unset_paths.extend(step_resp.state_patch.unset)
                        for k, v in step_resp.state_patch.inc.items():
                            inc_deltas[k] = inc_deltas.get(k, 0) + v
                    if step_resp.debug:
                        # Wrap node-level debug so it doesn't pollute step display
                        debug_log.append({
                            "step": step_type,
                            "ms": elapsed_ms,
                            "ok": True,
                            "node_debug": step_resp.debug,
                        })
                    else:
                        debug_log.append(
                            {"step": step_type, "ms": elapsed_ms, "ok": True}
                        )
            except asyncio.TimeoutError:
                debug_log.append(
                    {"step": step_type, "ms": self._step_timeout_ms, "ok": False, "error": "timeout"}
                )
                if not self._skip_on_error:
                    break
            except Exception as exc:
                debug_log.append(
                    {"step": step_type, "ok": False, "error": str(exc)}
                )
                if not self._skip_on_error:
                    break

        state_patch = None
        if merged_patches or unset_paths or inc_deltas:
            state_patch = StatePatch(
                set=merged_patches, unset=unset_paths, inc=inc_deltas
            )
            try:
                await self._state.apply_patch(session_id, state_patch)
            except Exception:
                pass

        final_text = ""
        for action in merged_actions:
            if action.type == "text.send":
                final_text = action.params.get("text", "")

        return Response(
            ts=self._now_ms(),
            text=final_text,
            actions=merged_actions,
            state_patch=state_patch,
            debug={"pipeline": debug_log} if debug_log else None,
        )

    async def _dispatch_step(
        self,
        session_id: str,
        event: Event,
        envelope: Envelope,
        step_type: str,
        context: Dict[str, Any],
    ) -> Optional[Response]:
        handler = self._forward_handlers.get(step_type)
        if not handler:
            return None
        enriched_data = dict(context)
        try:
            return await asyncio.wait_for(
                handler(event, envelope, step_type, enriched_data),
                timeout=self._step_timeout_ms / 1000,
            )
        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            return Response(
                ts=self._now_ms(),
                text="",
                debug={"step": step_type, "error": str(exc)},
            )

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)
