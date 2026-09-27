"""Offline provider for tests and CI - no network, no key. NOT a vision model:
it reads the hand-labelled manifest (data/images/manifest.json) to produce tags, so it exercises the
pipeline, guard and API deterministically. Real quality numbers must come from AI_PROVIDER=gemini."""
import hashlib
import json
import math
import os
import re
from ..config import settings
from ..schemas import ImageTags, PostTopic
from ..taxonomy import expand_synonyms, known_subject
from .base import ProviderError, Usage

DIM = 256


class MockProvider:
    def __init__(self):
        path = os.path.join(settings.images_dir, "manifest.json")
        self.manifest = {}
        if os.path.exists(path):
            with open(path) as f:
                self.manifest = {m["filename"]: m for m in json.load(f)["images"]}

    def describe_image(self, path: str):
        name = os.path.basename(path)
        m = self.manifest.get(name)
        if m is None:
            raise ProviderError(f"mock: {name} not in manifest", retryable=False)
        if m.get("mock_invalid_output"):          # simulate a model returning broken JSON
            try:
                ImageTags.model_validate_json('{"subject": "fox"}')
            except Exception as e:
                raise ProviderError(f"schema validation failed: {str(e)[:120]}")
        subject = m["label"]
        tags = ImageTags(subject=subject, category=m.get("category", "animal"),
                         attributes=m.get("attributes") or [subject, "outdoor"],
                         caption=m.get("caption") or f"A photo of a {subject}.",
                         confidence=m.get("mock_confidence", 0.93))
        return tags, Usage("mock-vision", 258, 60)

    def analyze_post(self, title: str, body: str):
        text = f"{title} {body}".lower()
        subj = known_subject(title) or known_subject(text)
        if subj:
            return PostTopic(subject=subj, category="animal", keywords=[]), Usage("mock-text", len(text) // 4, 20)
        return PostTopic(subject=title.split()[-1].lower().strip("?"), category="other", keywords=[]), Usage("mock-text", len(text) // 4, 20)

    def embed(self, texts: list[str]):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"[a-z]+", expand_synonyms(t).lower()):
                if len(w) < 3:
                    continue
                h = int(hashlib.md5(w.encode()).hexdigest(), 16)
                v[h % DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out, Usage("mock-embed", sum(len(t) for t in texts) // 4, 0)
