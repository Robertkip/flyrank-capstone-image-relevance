"""CI/offline only: creates placeholder files + manifest so the whole pipeline runs with AI_PROVIDER=mock.
These are NOT real photos; real results require scripts/download_images.py + AI_PROVIDER=gemini."""
import json
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else os.getenv("IMAGES_DIR", "./data/images")
PLAN = [("red fox", 10), ("gray wolf", 10), ("dog", 8), ("brown bear", 8), ("deer", 8)]


def main():
    os.makedirs(OUT, exist_ok=True)
    images = []
    for label, n in PLAN:
        for k in range(1, n + 1):
            name = f"{label.replace(' ', '-')}-{k:02d}.jpg"
            open(os.path.join(OUT, name), "wb").write(f"placeholder {name}".encode())
            images.append({"filename": name, "label": label, "category": "animal", "license": "placeholder (mock)",
                           "caption": f"A {label} in its natural habitat.", "attributes": [label, "wildlife", "outdoor"]})
    for k in (1, 2):   # ambiguous shots -> low confidence -> must be flagged
        name = f"hard-fox-{k:02d}.jpg"
        open(os.path.join(OUT, name), "wb").write(f"placeholder {name}".encode())
        images.append({"filename": name, "label": "fox", "category": "animal", "license": "placeholder (mock)",
                       "caption": "A blurry canine shape at night, possibly a fox.", "attributes": ["night", "blurry"],
                       "mock_confidence": 0.41})
    json.dump({"images": images}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    print(f"mock corpus: {len(images)} placeholder images in {OUT}")


if __name__ == "__main__":
    main()
