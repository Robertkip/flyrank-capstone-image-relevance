"""The mismatch guard: decides whether a ranked candidate is actually good enough, and explains why.
Pure logic, no I/O - easy to unit test. Rules run in order; every failed rule adds a reason."""
from dataclasses import dataclass, field
from .config import settings
from .taxonomy import canonical


@dataclass
class Verdict:
    accepted: bool
    reasons: list[str] = field(default_factory=list)


def subjects_match(post_subject: str | None, image_subject: str | None, subject_sim: float | None) -> tuple[bool, str]:
    p, i = canonical(post_subject), canonical(image_subject)
    if not p or not i:
        return False, "subject unknown"
    if p == i:
        return True, f"subject match ({i})"
    if subject_sim is not None and subject_sim >= settings.subject_similarity:
        return True, f"related subjects ({post_subject} ~ {image_subject}, {subject_sim:.2f})"
    return False, f"expected {p}, detected {i}"


def check(*, post_subject, post_category, image_subject, image_category, confidence, flagged,
          similarity, subject_sim=None, threshold=None) -> Verdict:
    threshold = settings.similarity_threshold if threshold is None else threshold
    bad: list[str] = []
    if flagged or confidence < settings.min_confidence:
        bad.append(f"Low-confidence classification ({confidence:.2f} < {settings.min_confidence:.2f}); needs human review")
    if post_category and image_category and post_category != image_category:
        bad.append(f"Category mismatch: expected {post_category}, detected {image_category}")
    ok_subject, why = subjects_match(post_subject, image_subject, subject_sim)
    if not ok_subject:
        label = (post_category or "subject").capitalize()
        bad.append(f"{label} category mismatch: {why}" if post_category == image_category else f"Subject mismatch: {why}")
    if similarity < threshold:
        bad.append(f"Semantic similarity {similarity:.2f} below threshold {threshold:.2f}")
    if bad:
        return Verdict(False, bad)
    return Verdict(True, [why, f"similarity {similarity:.2f} >= {threshold:.2f}", f"vision confidence {confidence:.2f}"])
