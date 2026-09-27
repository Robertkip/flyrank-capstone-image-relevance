"""Download a small, licence-free corpus from Pexels (free API key, no card: https://www.pexels.com/api/).
Writes data/images/<label>-NN.jpg + data/images/manifest.json (source URL, photographer, licence, ground-truth label).
Ground-truth labels come from the search query - eyeball the images and fix any wrong label in manifest.json."""
import json
import os
import sys
import time
import httpx
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("PEXELS_API_KEY")
OUT = os.getenv("IMAGES_DIR", "./data/images")
# label, pexels query, how many
PLAN = [
    ("red fox", "red fox wildlife", 10),
    ("gray wolf", "gray wolf wildlife", 10),
    ("dog", "dog portrait", 8),
    ("brown bear", "brown bear wildlife", 8),
    ("deer", "deer wildlife", 8),
    ("fox", "fox at night blurry", 2),   # deliberately hard: expected to come back low-confidence
]
LICENSE = "Pexels License (free to use) https://www.pexels.com/license/"


def main():
    if not KEY:
        sys.exit("Set PEXELS_API_KEY in .env (free, no credit card) - or drop your own photos + manifest into data/images/")
    os.makedirs(OUT, exist_ok=True)
    client = httpx.Client(headers={"Authorization": KEY}, timeout=30)
    images, seen = [], set()
    for label, query, n in PLAN:
        r = client.get("https://api.pexels.com/v1/search", params={"query": query, "per_page": n * 2, "orientation": "landscape"})
        r.raise_for_status()
        count = 0
        for p in r.json()["photos"]:
            if count >= n or p["id"] in seen:
                continue
            seen.add(p["id"])
            name = f"{label.replace(' ', '-')}-{count + 1:02d}.jpg" if query != "fox at night blurry" else f"hard-fox-{count + 1:02d}.jpg"
            img = client.get(p["src"]["medium"])          # ~350px tall: small repo, cheap vision calls
            img.raise_for_status()
            open(os.path.join(OUT, name), "wb").write(img.content)
            images.append({"filename": name, "label": label, "category": "animal", "source_url": p["url"],
                           "photographer": p["photographer"], "license": LICENSE})
            count += 1
            time.sleep(0.2)
        print(f"{label:12s} {count} images")
    json.dump({"images": images}, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)
    print(f"wrote {len(images)} images + manifest.json to {OUT}")


if __name__ == "__main__":
    main()
