# Design doc: AI Image Understanding & Content Matching Engine

## Problem
Editors need the right image for each article. Filename or keyword search picks the wrong photo (a wolf for a fox article). We want **good suggestions when confident, and a safe, explained refusal when not**.

## Data model
| Table | Purpose | Key indexes |
|---|---|---|
| `images` | one row per file (content hash, licence, status: pending/tagged/flagged/failed) | unique `(tenant_id, sha256)`, `(tenant_id, status)` |
| `image_tags` | validated vision output: subject, category, attributes, caption, confidence, flagged | `subject`, `category`, unique `image_id` |
| `posts` | article + extracted topic (subject, category) | unique `(tenant_id, slug)` |
| `embeddings` | vectors for images, posts and subject names (JSON arrays, fine at ~50 images) | unique `(owner_type, owner_key, model)` |
| `suggestions` | ranked post-image pair + guard verdict + reasons | unique `(post_id, image_id)`, `(post_id, rank)` |
| `reviews` | human approve/reject decisions | `suggestion_id` |
| `jobs` | batch job progress, errors, idempotency key | unique `(tenant_id, kind, idempotency_key)` |
| `cost_log` | one row per AI call attempt: model, target, tokens, estimated USD | `job_id`, `created_at` |

## Tag schema (validated with Pydantic)
`{subject: str, category: animal|plant|food|landscape|person|object|other, attributes: [str] (1-8), caption: str, confidence: 0-1}`. Gemini is asked for exactly this JSON schema (`responseSchema`), and the answer is **still** validated. Invalid output → retry → the image is marked `failed`, never stored. `confidence < 0.60` → `flagged`.

## Matching strategy
1. Embed image text (`subject + caption + attributes`) and post text (`title + body`) with the same model (`SEMANTIC_SIMILARITY`).
2. Rank all tagged images for a post by cosine similarity.
3. Every candidate goes through the **mismatch guard**. The best *accepted* candidate is the suggestion. If none is accepted → `no_confident_match` + reasons.

## Guard rules (all must pass)
1. **Confidence:** the vision confidence is ≥ `MIN_CONFIDENCE` and the image isn't flagged.
2. **Category:** the post category equals the image category.
3. **Subject:** the canonical subjects are equal (alias table: "Vulpes vulpes" → fox, "gray wolf" → wolf), **or** the subject-name embeddings are ≥ `SUBJECT_SIMILARITY` apart.
4. **Similarity:** the post–image cosine is ≥ `SIMILARITY_THRESHOLD`, tuned on the eval set with `scripts/eval.py --sweep`.

Every failed rule adds a human-readable reason, e.g. `Animal category mismatch: expected fox, detected wolf`.

## API surface
`POST /jobs/ingest-images`, `POST /jobs/process-posts`, `GET /jobs/{id}`, `GET /images`, `POST /posts`, `GET /posts/{id}/images`, `GET /posts/{id}/images/{image_id}/check`, `GET /suggestions/{id}`, `POST /suggestions/{id}/review`, `GET /review`, `GET /costs`.

## Layers
`app/main.py` (HTTP, validation) → `app/matching.py`, `app/guard.py`, `app/jobs.py` (logic) → `app/db.py` (data) and `app/providers/*` (AI adapters: Gemini, or an offline mock for tests).

## Non-goal
No frontend build, no image upload UI, and no model comparison. The review UI is a plain HTML table plus JSON endpoints.
