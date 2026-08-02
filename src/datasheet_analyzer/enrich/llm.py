"""LLM client interface + implementations.

The enrich stage goes through this interface so tests inject a fake and a
different provider can be added without touching callers (mirrors the
Lit_Analyzer convention).
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, prompt: str, max_tokens: int) -> str: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("AnthropicClient requires an API key")
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        *,
        image_bytes: bytes | None = None,
        image_media_type: str = "image/png",
    ) -> str:
        content: list[dict] = []
        if image_bytes:
            import base64

            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_media_type,
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": prompt})
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


class FakeClient:
    """Test double: records calls, returns a canned JSON-ish response."""

    def __init__(self, response: str = "{}", model: str = "fake-1"):
        self.response = response
        self.model = model
        self.calls: list[tuple[str, str, int]] = []

    def complete(
        self,
        system: str,
        prompt: str,
        max_tokens: int,
        *,
        image_bytes: bytes | None = None,
        image_media_type: str = "image/png",
    ) -> str:
        self.calls.append((system, prompt, max_tokens))
        return self.response
