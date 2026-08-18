from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MemoryStore:
    store: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    async def load(self, conversation_id: str) -> list[dict[str, Any]]:
        return self.store.get(conversation_id, [])

    async def append(self, conversation_id: str, item: dict[str, Any]) -> None:
        self.store.setdefault(conversation_id, []).append(item)
