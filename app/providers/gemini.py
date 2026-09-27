"""Gemini Flash (free tier) via REST: structured vision output + embeddings."""
import base64
import json
import mimetypes
import httpx
from pydantic import ValidationError
from ..config import settings
from ..schemas import ImageTags, PostTopic
from .base import ProviderError, Usage

BASE = "https://generativelanguage.googleapis.com/v1beta/models"
CATS = ["animal", "plant", "food", "landscape", "person", "object", "other"]

TAG_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "subject": {"type": "STRING", "description": "Common name of the single main subject, specific species if identifiable, e.g. 'red fox', 'gray wolf', 'golden retriever'"},
        "category": {"type": "STRING", "enum": CATS},
        "attributes": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "3-6 short visual attributes"},
        "caption": {"type": "STRING", "description": "One factual sentence describing the image"},
        "confidence": {"type": "NUMBER", "description": "0-1: how sure you are about the subject identification"},
    },
    "required": ["subject", "category", "attributes", "caption", "confidence"],
}
TOPIC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "subject": {"type": "STRING", "description": "Common name of the main subject of the article, e.g. 'red fox'"},
        "category": {"type": "STRING", "enum": CATS},
        "keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["subject", "category", "keywords"],
}
VISION_PROMPT = ("Identify the single main subject of this photo for an image library. Be specific about the species. "
                 "Do not guess: if the subject is blurry, partly hidden, or could be one of several similar species "
                 "(e.g. fox vs coyote vs wolf), lower the confidence accordingly (below 0.6).")
TOPIC_PROMPT = "What is the main subject of this blog post? Use the common English name.\n\nTITLE: {title}\n\n{body}"


class GeminiProvider:
    def __init__(self):
        if not settings.gemini_api_key:
            raise ProviderError("GEMINI_API_KEY is not set (see .env.example)", retryable=False)
        self.http = httpx.Client(timeout=60, headers={"x-goog-api-key": settings.gemini_api_key})

    def _post(self, url: str, body: dict) -> dict:
        try:
            r = self.http.post(url, json=body)
        except httpx.HTTPError as e:
            raise ProviderError(f"network error: {e}")
        if r.status_code in (400, 401, 403, 404):
            raise ProviderError(f"Gemini {r.status_code}: {r.text[:200]}", retryable=False)
        if r.status_code >= 300:
            raise ProviderError(f"Gemini {r.status_code}: {r.text[:200]}")   # 429/5xx -> retry
        return r.json()

    def _generate(self, parts: list, schema: dict) -> tuple[str, Usage]:
        data = self._post(f"{BASE}/{settings.vision_model}:generateContent", {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "responseSchema": schema},
        })
        um = data.get("usageMetadata", {})
        usage = Usage(settings.vision_model, um.get("promptTokenCount", 0),
                      um.get("candidatesTokenCount", 0) + um.get("thoughtsTokenCount", 0))
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise ProviderError(f"empty response ({data.get('promptFeedback') or 'no candidates'})")
        return text, usage

    def describe_image(self, path: str) -> tuple[ImageTags, Usage]:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        text, usage = self._generate([{"inline_data": {"mime_type": mime, "data": b64}}, {"text": VISION_PROMPT}], TAG_SCHEMA)
        try:
            return ImageTags.model_validate_json(text), usage      # never trust unvalidated output
        except ValidationError as e:
            raise ProviderError(f"schema validation failed: {e.errors()[:2]}")

    def analyze_post(self, title: str, body: str) -> tuple[PostTopic, Usage]:
        text, usage = self._generate([{"text": TOPIC_PROMPT.format(title=title, body=body[:6000])}], TOPIC_SCHEMA)
        try:
            return PostTopic.model_validate_json(text), usage
        except ValidationError as e:
            raise ProviderError(f"schema validation failed: {e.errors()[:2]}")

    def embed(self, texts: list[str]) -> tuple[list[list[float]], Usage]:
        model = settings.embedding_model
        data = self._post(f"{BASE}/{model}:batchEmbedContents", {"requests": [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]}, "taskType": "SEMANTIC_SIMILARITY",
             "outputDimensionality": 768} for t in texts]})
        vecs = [e["values"] for e in data.get("embeddings", [])]
        if len(vecs) != len(texts):
            raise ProviderError("embedding count mismatch")
        # The embeddings API does not return token counts; estimate ~4 chars/token for cost tracking.
        return vecs, Usage(model, sum(len(t) for t in texts) // 4, 0)
