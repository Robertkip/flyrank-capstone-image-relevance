# EVIDENCE

One proof per requirement in Section 6 of the brief.

> **Read this first.** The proofs below were produced with `AI_PROVIDER=mock`: an offline stand-in that reads hand labels from the manifest instead of calling a vision model, over placeholder files. They prove the **pipeline, guard, API, retries, idempotency and cost logging** work end to end. They do **not** prove vision quality.
> **Before submitting:** run the real pipeline (`AI_PROVIDER=gemini` + `scripts/download_images.py`), then replace every block marked 🔁 with real output. The real top-1 precision goes in the README.

Test suite (26 tests, mock provider), `python -m pytest -v`:
```
tests/test_api.py::test_bad_input_is_4xx_not_500 PASSED
tests/test_api.py::test_create_post_is_idempotent_by_slug PASSED
tests/test_api.py::test_review_approve_is_idempotent_and_inspectable PASSED
tests/test_api.py::test_overriding_a_guard_rejection_requires_a_note PASSED
tests/test_api.py::test_tenants_are_isolated PASSED
tests/test_api.py::test_ingest_job_idempotency_key PASSED
tests/test_guard.py::test_wolf_on_fox_post_is_rejected_with_explanation PASSED
tests/test_guard.py::test_fox_on_fox_post_is_accepted PASSED
tests/test_guard.py::test_scientific_name_matches_common_name PASSED
tests/test_guard.py::test_low_confidence_is_rejected_even_if_subject_matches PASSED
tests/test_guard.py::test_similarity_below_threshold_is_rejected PASSED
tests/test_guard.py::test_different_category_is_rejected PASSED
tests/test_probes.py::test_probe1_batch_tags_every_image_and_flags_low_confidence PASSED
tests/test_probes.py::test_probe2_fox_post_ranks_fox_first PASSED
tests/test_probes.py::test_probe2b_synonym_post_finds_fox PASSED
tests/test_probes.py::test_probe3_forced_wolf_is_rejected PASSED
tests/test_probes.py::test_probe4_no_suitable_image PASSED
tests/test_probes.py::test_probe6_every_ai_call_has_a_cost_entry PASSED
tests/test_retries.py::test_transient_failure_is_retried_and_each_attempt_costed PASSED
tests/test_retries.py::test_invalid_output_after_retries_raises_and_is_not_stored PASSED
tests/test_schema.py::test_valid_output_is_parsed_and_normalised PASSED
tests/test_schema.py::test_invalid_model_output_is_never_trusted
tests/test_schema.py::test_invalid_model_output_is_never_trusted
tests/test_schema.py::test_invalid_model_output_is_never_trusted
tests/test_schema.py::test_invalid_model_output_is_never_trusted
tests/test_schema.py::test_invalid_model_output_is_never_trusted
============================== 26 passed in 0.84s ==============================
```

## AI processing

**☑ Vision output is validated against a schema; invalid responses are never trusted.**
`app/schemas.py::ImageTags` (Pydantic) + Gemini `responseSchema`; `model_validate_json` runs on every response in `app/providers/gemini.py`.
```
tests/test_schema.py::test_invalid_model_output_is_never_trusted  (5 cases: missing fields, confidence 1.7, bad enum, empty attributes, prose)  PASSED
tests/test_retries.py::test_invalid_output_after_retries_raises_and_is_not_stored  PASSED
```

**☑ Low-confidence classifications are flagged instead of accepted.** 🔁 `GET /images?status=flagged`
```json
[
 {
  "id": 35,
  "filename": "hard-fox-01.jpg",
  "status": "flagged",
  "license": "placeholder (mock)",
  "source_url": null,
  "tags": {
   "subject": "fox",
   "category": "animal",
   "attributes": [
    "night",
    "blurry"
   ],
   "caption": "A blurry canine shape at night, possibly a fox.",
   "confidence": 0.41,
   "flagged": true,
   "flag_reason": "confidence 0.41 < 0.60",
   "model": "mock-vision"
  }
 },
 {
  "id": 36,
  "filename": "hard-fox-02.jpg",
  "status": "flagged",
  "license": "placeholder (mock)",
  "source_url": null,
  "tags": {
   "subject": "fox",
   "category": "animal",
   "attributes": [
    "night",
    "blurry"
   ],
   "caption": "A blurry canine shape at night, possibly a fox.",
   "confidence": 0.41,
   "flagged": true,
   "flag_reason": "confidence 0.41 < 0.60",
   "model": "mock-vision"
  }
 }
]
```

**☑ Images are processed through a batch background job with retries.** 🔁 `python -m scripts.seed`
```
ingest_images: status=done processed=46/46 flagged=2 failed=0
process_posts: status=done processed=14/14 flagged=0 failed=0
```
Retry proof: `tests/test_retries.py::test_transient_failure_is_retried_and_each_attempt_costed` (two 503s, then success → cost rows `[(1, False), (2, False), (3, True)]`) PASSED.

**☑ Vision and embedding costs are tracked per call.** 🔁 `GET /costs?limit=3`
```json
{
 "budget_usd": 1.0,
 "spent_est_usd": 0.011698,
 "note": "Estimated at paid list prices; on the Gemini free tier the actual charge is $0.",
 "by_kind": [
  {
   "kind": "embedding",
   "calls": 62,
   "input_tokens": 1817,
   "output_tokens": 0,
   "est_usd": 0.000273
  },
  {
   "kind": "text",
   "calls": 14,
   "input_tokens": 885,
   "output_tokens": 280,
   "est_usd": 0.000965
  },
  {
   "kind": "vision",
   "calls": 46,
   "input_tokens": 11868,
   "output_tokens": 2760,
   "est_usd": 0.01046
  }
 ],
 "calls": [
  {
   "id": 122,
   "job_id": 2,
   "kind": "embedding",
   "model": "mock-embed",
   "target": "subjects:5",
   "ok": true,
   "attempt": 1,
   "input_tokens": 6,
   "output_tokens": 0,
   "est_usd": 9e-07
  },
  {
   "id": 121,
   "job_id": 2,
   "kind": "embedding",
   "model": "mock-embed",
   "target": "post:14",
   "ok": true,
   "attempt": 1,
   "input_tokens": 64,
   "output_tokens": 0,
   "est_usd": 9.6e-06
  },
  {
   "id": 120,
   "job_id": 2,
   "kind": "text",
   "model": "mock-text",
   "target": "post:14",
   "ok": true,
   "attempt": 1,
   "input_tokens": 63,
   "output_tokens": 20,
   "est_usd": 6.89e-05
  }
 ]
}
```

## Matching system

**☑ Image and post embeddings are stored; posts return ranked suggestions.** 🔁 `GET /posts/1/images?limit=46` (red-fox post), best result per subject:
```
decision: match best: red-fox-01.jpg 0.3331
  best red fox    rank  1 sim 0.333 accepted
  best fox        rank 11 sim 0.128 rejected
  best deer       rank 13 sim 0.025 rejected
  best dog        rank 21 sim 0.025 rejected
  best brown bear rank 29 sim 0.018 rejected
  best gray wolf  rank 37 sim 0.018 rejected
```

**☑ Semantic matching works for equivalent concepts.** 🔁 Post "What does Vulpes vulpes eat?" → `GET /posts/2/images`
```
fox match red-fox-01.jpg ['subject match (fox)', 'similarity 0.28 >= 0.25', 'vision confidence 0.93']
```

## Safety layer

**☑ The guard rejects the wolf on the fox post.** 🔁 `GET /posts/1/images/<wolf id>/check`
```
gray-wolf-01.jpg rejected ['Animal category mismatch: expected fox, detected wolf', 'Semantic similarity 0.02 below threshold 0.25']
```

**☑ Rejections include a human-readable explanation.** See above, plus `tests/test_guard.py` (6 tests) PASSED.

**☑ "No confident match" with reasons.** 🔁 Post "How to make a sourdough starter at home" → `GET /posts/12/images`
```
no_confident_match [
 "No image cleared the guard (46 checked).",
 "Best candidate #35 (fox): Low-confidence classification (0.41 < 0.60); needs human review; Category mismatch: expected other, detected animal; Subject mismatch: expected home, detected fox; Semantic similarity 0.03 below threshold 0.25"
]
```

## Backend

**☑ Database models for images, tags, embeddings, posts, suggestions, approvals/rejections, with indexes.** See `app/db.py` and the table in `docs/DESIGN.md`. Created by the versioned migration `app/migrations.py` (`001_initial_schema`).

**☑ API validated; review workflow (approve / reject / inspect why).**
Bad input → 4xx (`POST /posts` with a too-short body, unknown post, bad tenant header):
```
422 404 400
```
Approve the best suggestion twice (idempotent), then inspect:
```
1 approved ['subject match (fox)', 'similarity 0.33 >= 0.25', 'vision confidence 0.93']
replay: True reviews: 1
```
Job idempotency (the same `Idempotency-Key` twice → 202, then 200 replay of the same job):
```
:"2026-09-27T07:48:17.698334+00:00","finished_at":null} 202
t":"2026-09-27T07:48:17.698334","finished_at":"2026-09-27T07:48:17.717034"} 200
```

## Quality & documentation

**☑ Labelled eval set measures top-1 precision.** 🔁 `python -m scripts.eval --sweep` (14 posts in `data/eval.json`: 11 with a correct answer, 3 with none)
```
Top-1 precision: 9/11 = 0.818   |   correct 'no confident match': 3/3   (threshold 0.25, provider mock)
```
The two misses are **safe refusals**, not wrong images: the mock's bag-of-words vectors scored those posts below threshold.

**☑ README with architecture diagram; required files present.** `README.md`, `capstone.yaml`, `EVIDENCE.md`, `BUILDLOG.md`, `.env.example`, `LICENSE`, `docs/DESIGN.md`.
