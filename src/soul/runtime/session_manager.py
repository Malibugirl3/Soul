from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from ..contracts.state import SoulState


class SessionManager:
    """
    Persistent per-session SoulState.

    Strategy A:
    - Every state update immediately flushed to disk.
    - Each session stored as a single JSON file.
    """
    def __init__(self) -> None:
        self._sessions: Dict[str, SoulState] = {}
        self._storage_dir = Path("data")
        self._storage_dir.mkdir(exist_ok=True) 

    def _file_path(self, session_id: str) -> Path:
        # Avoid illegal filename chars like ":" on Windows
        safe_id = session_id.replace(":", "_")  # TODO: The more comprehensive safe-checking method
        return self._storage_dir / f"{safe_id}.json"

    def get_or_create(self, session_id: str) -> SoulState:
        if session_id in self._sessions:
            return self._sessions[session_id]
        
        file_path = self._file_path(session_id)

        if file_path.exists():
            data = json.loads(file_path.read_text(encoding="utf-8"))
            state = SoulState.model_validate(data)
        else:
            state = SoulState(session_id=session_id)

        self._sessions[session_id] = state
        return state
    
    def set(self, state: SoulState) -> None:
        self._sessions[state.session_id] = state

        file_path = self._file_path(state.session_id)

        file_path.write_text(
            json.dumps(
                state.model_dump(),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )