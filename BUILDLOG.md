# BUILDLOG: AI usage log

Honest record of where AI tools helped, where they were wrong, and what I changed.

| Date | Where AI helped | What was wrong / what I changed |
|---|---|---|
| 2026-09-27 | Claude generated the initial project skeleton: FastAPI layers, SQLAlchemy models, Gemini REST adapter, guard, batch jobs, tests, docs. | Reviewed every module before committing. |
| 2026-09-27 | Mock provider for offline tests. | **Bug found by tests:** the mock's topic extraction treated "foxes" (plural) as an unknown subject, so the fox post's topic came out as the raw title. Fixed by adding plural aliases and a `known_subject()` helper that returns a subject only if an alias really appears in the text. |
| 2026-09-27 | Threshold defaults. | **Wrong assumption:** a single `SIMILARITY_THRESHOLD` doesn't work across embedding models. The offline bag-of-words vectors peak around 0.3, while Gemini embeddings sit much higher, so the Gemini default (0.62) refused every fox match in mock mode. Changed the threshold to be per-environment (tests set 0.25), and the README requires tuning it with `scripts/eval.py --sweep` on the real model. |
| 2026-09-27 | Guard wording. | Adjusted the subject-mismatch message to the brief's format ("Animal category mismatch: expected fox, detected wolf") and added a test asserting it word for word. |
| _add yours_ | _e.g. first real Gemini run: which images were mis-tagged, what you changed in the prompt or threshold_ | |

Code I can explain line by line: `app/guard.py::check` (rule order and why confidence is checked first), `app/jobs.py::with_retries` (budget check before every attempt, cost row per attempt, no retry on non-retryable errors), `app/matching.py::rank_for_post` (rank by similarity, but the suggestion is the best *accepted* candidate).
