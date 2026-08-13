"""Opt-in OpenRouter vision OCR fallback for unresolved semantic crops only."""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import cv2
import httpx
import numpy as np
from numpy.typing import NDArray

from nexus_v2.ocr.types import OCRCandidate


class OpenRouterVisionOCR:
    """Transcribe one tight crop through an explicitly configured vision model."""

    def __init__(
        self,
        *,
        model: str = "google/gemini-3.1-flash-lite-preview",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise ValueError("OPENROUTER_API_KEY is required for opt-in vision OCR")
        self.model = model
        self.name = f"openrouter:{model}"
        self._client = client or httpx.Client(
            base_url="https://openrouter.ai/api/v1",
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {key}"},
        )

    def recognize(self, image: NDArray[np.uint8], *, parser: str) -> OCRCandidate | None:
        encoded = self._encode_crop(image)
        prompt = (
            "Transcribe only the text visible in this tight game-UI crop. "
            "Preserve Unicode letters, symbols, capitalization, digits, punctuation, "
            "and spacing exactly. "
            "Do not infer hidden text and do not explain. "
            f"The expected semantic parser is {parser!r}. "
            'Return exactly one JSON object: {"text": string|null}.'
        )
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            content = self._extract_content(body)
            parsed = json.loads(content)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        text = parsed.get("text") if isinstance(parsed, dict) else None
        if not isinstance(text, str) or not text.strip():
            return None
        return OCRCandidate(
            raw=text.strip(),
            confidence=0.0,
            backend=self.name,
            preprocessing="native-tight-crop",
        )

    @staticmethod
    def _encode_crop(image: NDArray[np.uint8]) -> str:
        bgr = image
        if image.ndim == 3:
            bgr = np.asarray(cv2.cvtColor(image, cv2.COLOR_RGB2BGR), dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", bgr)
        if not ok:
            raise ValueError("failed to encode OCR fallback crop")
        return base64.b64encode(encoded.tobytes()).decode("ascii")

    @staticmethod
    def _extract_content(body: Any) -> str:
        if not isinstance(body, dict):
            raise TypeError("OpenRouter response must be an object")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise TypeError("choice must be an object")
        message = first.get("message")
        if not isinstance(message, dict):
            raise TypeError("message must be an object")
        content = message.get("content")
        if not isinstance(content, str):
            raise TypeError("message content must be a string")
        return content
