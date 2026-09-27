# AI Image Understanding & Content Matching Engine

FlyRank Internship · Backend Track · Capstone (`flyrank-capstone-image-relevance`)

This service looks at an image library, works out what is actually in each photo, and matches the right image to each blog post. A red-fox article gets the red-fox photo, never the wolf. When no image is good enough, it says **"no confident match"** and explains why instead of guessing.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL (Docker) · Pydantic · Gemini Flash (vision + embeddings, free tier) · pytest.

## Results

| Metric | Value | How to reproduce |
|---|---|---|
| **Top-1 precision (Gemini)** | **_run `scripts.eval` after your real ingest and paste here_** | `docker compose exec app python -m scripts.eval --sweep` |
| Correct "no confident match" on 3 no-answer posts | _paste_ | same command |
| Pipeline check (offline mock provider, 14 posts) | 9/11 top-1, 3/3 refusals, 26/26 tests | `AI_PROVIDER=mock python -m pytest -q` |

> The mock numbers only prove the pipeline, guard and API behave correctly. They are **not** a vision-quality number, because the mock reads hand labels instead of looking at the photos. The headline number must come from the Gemini run.

## Architecture

```
                         ┌──────────── batch job (background thread, retries, cost log, budget guard) ────────────┐
 data/images/*.jpg ──►   │ Gemini Flash vision ──► Pydantic ImageTags ──► confidence < 0.60 ? flagged : tagged    │
 (Pexels, licensed)      │        {subject, category, attributes, caption, confidence}   ──► image_tags           │
                         │ embed(subject + caption + attributes) ─────────────────────────► embeddings (image)   │
                         └────────────────────────────────────────────────────────────────────────────────────────┘
 POST /posts ──► posts ──► batch job: Gemini topic {subject, category} + embed(title + body) ──► embeddings (post)

 GET /posts/:id/images
    └─► similarity ranking (cosine: post vector × every image vector)          app/matching.py
          └─► MISMATCH GUARD, per candidate                                    app/guard.py
                1. vision confidence ≥ MIN_CONFIDENCE and not flagged
                2. same category (animal / food / …)
                3. same canonical subject ("Vulpes vulpes" = "red fox" = fox)  app/taxonomy.py
                   or subject-name embeddings ≥ SUBJECT_SIMILARITY
                4. cosine ≥ SIMILARITY_THRESHOLD (tuned on the eval set)
          ├─► "match": best accepted image + reasons
          └─► "no_confident_match": reasons from the best candidate
                 └─► suggestions table ──► Review API: approve / reject / inspect why
```

**Layers:** `app/main.py` (HTTP + validation) → `app/matching.py`, `app/guard.py`, `app/jobs.py` (logic) → `app/db.py` (data) and `app/providers/` (Gemini adapter; offline mock for tests). The design doc is in `docs/DESIGN.md`.

## Run it

You need Docker, a **free** Gemini key (<https://aistudio.google.com/apikey>) and a **free** Pexels key (<https://www.pexels.com/api/>). Neither asks for a card.

```bash
cp .env.example .env                                   # add GEMINI_API_KEY and PEXELS_API_KEY
python -m pip install httpx python-dotenv && python scripts/download_images.py   # ~46 licensed images + manifest.json
docker compose up --build -d                           # run: API on http://localhost:8000
docker compose exec app python -m scripts.seed         # seed: 14 posts + tag/embed all images (background jobs)
docker compose exec app python -m scripts.eval --sweep # eval: top-1 precision + threshold sweep
docker compose exec app python -m pytest -q            # tests (offline, mock provider)
```

Then try:

```bash
curl localhost:8000/images?status=flagged                   # probe 1: low-confidence images flagged
curl localhost:8000/posts                                    # find the post ids
curl "localhost:8000/posts/1/images?limit=10"                # probe 2: fox article → fox first
curl localhost:8000/posts/1/images/<wolf_image_id>/check     # probe 3: wolf rejected, with reason
curl localhost:8000/posts/12/images                          # probe 4: sourdough → no confident match
curl localhost:8000/costs                                    # probe 6: every AI call with a cost row
open  http://localhost:8000/review                           # review table
curl -X POST localhost:8000/suggestions/<id>/review -H 'Content-Type: application/json' \
     -d '{"decision":"approve","reviewer":"robert"}'
```

**Without Docker:** `pip install -r requirements.txt`, set `DATABASE_URL=sqlite:///./data/app.db`, then run `uvicorn app.main:app` and the same `python -m scripts.*` commands.

**Offline and no keys** (pipeline demo only): `AI_PROVIDER=mock SIMILARITY_THRESHOLD=0.25 python -m scripts.make_mock_corpus && python -m scripts.seed`.

## API

| Method | Path | What it does |
|---|---|---|
| POST | `/jobs/ingest-images` | Start the batch job that tags and embeds new images. Accepts an `Idempotency-Key` header. Returns 202. |
| POST | `/jobs/process-posts` | Start the batch job that analyses and embeds pending posts. |
| GET | `/jobs/{id}` | Job progress: processed, flagged, failed, errors. |
| GET | `/images?status=` | Images with their validated tags. |
| POST / GET | `/posts` | Create posts (idempotent by slug) or list them. |
| GET | `/posts/{id}/images?limit=` | Ranked, guard-checked suggestions: `match` or `no_confident_match` with reasons. |
| GET | `/posts/{id}/images/{image_id}/check` | Force one candidate through the guard. |
| GET | `/suggestions/{id}` | Inspect why a pairing was selected or refused, plus its review history. |
| POST | `/suggestions/{id}/review` | Approve or reject. Idempotent. Overriding a guard rejection requires a note. |
| GET | `/review` | Minimal HTML review table. |
| GET | `/costs` | Per-call cost log, totals by kind, and the budget. |

Every endpoint accepts an optional `X-Tenant-Id` header (default `demo`). Data is isolated per tenant.

## Reliability details

- **Never trust model output:** Gemini is asked for a JSON schema, and every answer is still validated with Pydantic. Invalid output → retry → the image is marked `failed`, never stored.
- **Retries:** up to 3 attempts with exponential backoff on 429/5xx or network errors. No retry on 4xx such as a bad key.
- **Cost tracking:** one `cost_log` row per call attempt, with model, target, tokens and estimated USD at paid list prices. The actual charge on the free tier is $0. A budget guard stops jobs once `AI_BUDGET_USD` is reached.
- **Failure alert:** failed items and fatal job errors are logged at ERROR and appended to `data/alerts.log`.
- **Idempotency:** images are deduplicated by content hash; jobs accept an `Idempotency-Key`; posts are idempotent by slug; repeating a review decision doesn't create a duplicate.
- **Secrets:** read from the environment only; `.env` is git-ignored.

## Tuning the guard

The similarity threshold depends on the embedding model, so it has to be set from data, not guessed. `scripts/eval.py --sweep` prints top-1 precision and refusal accuracy for thresholds from 0.10 to 0.90. Pick the highest threshold that keeps top-1 precision high while every no-answer post is still refused, then set `SIMILARITY_THRESHOLD` in `.env`. The fox/wolf boundary is held mainly by the **subject rule**, not the threshold, so it holds even when a wolf photo scores a high similarity.

## Limitations

- About 50 images and one tenant for the demo. Vectors are stored as JSON and ranked in Python. That's fine at this size; at scale you'd use pgvector plus an ANN index.
- The subject alias table (`app/taxonomy.py`) covers the demo animals. Unknown subjects fall back to embedding similarity between subject names, which is stricter and may refuse valid matches.
- Ground-truth labels come from the Pexels search query in `manifest.json`. Check the images yourself and correct any wrong labels.
- The background worker is an in-process thread pool. A production system would use a queue such as Redis/RQ or Celery so jobs survive restarts.
- Vision confidence is the model's own estimate, so it's useful for flagging but not calibrated.

## Licence

MIT (`LICENSE`). Images are from Pexels under the Pexels License; each file's source is listed in `data/images/manifest.json`.
