from app import guard
from app.taxonomy import canonical

BASE = dict(post_subject="red fox", post_category="animal", image_category="animal", confidence=0.94, flagged=False)


def test_wolf_on_fox_post_is_rejected_with_explanation():
    v = guard.check(**BASE, image_subject="gray wolf", similarity=0.80)
    assert not v.accepted
    assert "Animal category mismatch: expected fox, detected wolf" in v.reasons


def test_fox_on_fox_post_is_accepted():
    v = guard.check(**BASE, image_subject="red fox", similarity=0.80)
    assert v.accepted and v.reasons[0] == "subject match (fox)"


def test_scientific_name_matches_common_name():
    assert canonical("Vulpes vulpes") == canonical("red fox") == "fox"
    v = guard.check(**{**BASE, "post_subject": "vulpes vulpes"}, image_subject="red fox", similarity=0.7)
    assert v.accepted


def test_low_confidence_is_rejected_even_if_subject_matches():
    v = guard.check(**{**BASE, "confidence": 0.41, "flagged": True}, image_subject="red fox", similarity=0.9)
    assert not v.accepted and any("Low-confidence" in r for r in v.reasons)


def test_similarity_below_threshold_is_rejected():
    v = guard.check(**BASE, image_subject="red fox", similarity=0.30, threshold=0.62)
    assert not v.accepted and any("below threshold" in r for r in v.reasons)


def test_different_category_is_rejected():
    v = guard.check(**{**BASE, "post_category": "food", "post_subject": "sourdough"}, image_subject="dog", similarity=0.2)
    assert not v.accepted and any("Category mismatch: expected food, detected animal" in r for r in v.reasons)
