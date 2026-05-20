from __future__ import annotations

import json
from typing import Dict, List, Optional, Set, Tuple

from ..contracts.capability import ActionSchema, CapabilityManifest


class ActionRegistry:
    """Catalog of all actions registered by nodes.

    Indexed by action_type -> {node_id -> ActionSchema} for O(1) lookup.
    Can generate a tool catalogue string for the ReasoningNode's LLM prompt.
    """

    def __init__(self) -> None:
        self._actions: Dict[str, Dict[str, ActionSchema]] = {}
        self._node_actions: Dict[str, Set[str]] = {}
        self._catalogue_cache: Optional[str] = None

    def register_manifest(self, manifest: CapabilityManifest) -> None:
        self.unregister_node(manifest.node_id)
        self._node_actions[manifest.node_id] = set()
        for action in manifest.actions:
            atype = action.action_type
            self._actions.setdefault(atype, {})[manifest.node_id] = action
            self._node_actions[manifest.node_id].add(atype)
        self._catalogue_cache = None

    def unregister_node(self, node_id: str) -> None:
        action_types = self._node_actions.pop(node_id, set())
        for atype in action_types:
            self._actions.get(atype, {}).pop(node_id, None)
            if not self._actions.get(atype):
                self._actions.pop(atype, None)
        if action_types:
            self._catalogue_cache = None

    def resolve(self, action_type: str) -> Optional[Tuple[str, ActionSchema]]:
        """Return (node_id, ActionSchema) for an action type, or None."""
        handlers = self._actions.get(action_type)
        if not handlers:
            return None
        node_id, schema = next(iter(handlers.items()))
        return node_id, schema

    def list_all(self) -> List[Tuple[str, str, ActionSchema]]:
        """Return all (node_id, action_type, ActionSchema) tuples."""
        result = []
        for atype, handlers in self._actions.items():
            for node_id, schema in handlers.items():
                result.append((node_id, atype, schema))
        return result

    def get_tool_catalogue(self) -> str:
        """Generate a compact tool list for injection into the LLM system prompt."""
        if self._catalogue_cache is not None:
            return self._catalogue_cache
        lines = ["Available actions:"]
        for atype, handlers in sorted(self._actions.items()):
            for schema in handlers.values():
                desc = schema.description
                params = json.dumps(schema.params_schema, ensure_ascii=False)
                lines.append(f"  {atype}: {desc}")
                if schema.params_schema:
                    lines.append(f"    params: {params}")
        self._catalogue_cache = "\n".join(lines)
        return self._catalogue_cache

    def count(self) -> int:
        return sum(len(h) for h in self._actions.values())
