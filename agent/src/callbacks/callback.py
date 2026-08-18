from __future__ import annotations

from dataclasses import dataclass
import logging

import httpx

from src.models import CallbackPayload


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CallbackClient:
    url: str | None

    async def send(self, payload: CallbackPayload) -> None:
        if not self.url:
            return
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.url, json=payload.model_dump())
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            # Callback delivery issues should not fail the main /agent/run response.
            logger.warning("Callback delivery failed for url=%s: %s", self.url, exc)
