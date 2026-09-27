"""Similarity ranking + guard -> explained suggestions. No AI calls here: vectors are precomputed by jobs."""
import math
from sqlalchemy import select
from .db import Embedding, Image, ImageTag, Post, Suggestion
from . import guard


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _vec(db, owner_type, key):
    return db.scalar(select(Embedding.vector).where(Embedding.owner_type == owner_type, Embedding.owner_key == str(key)))


def evaluate_pair(db, post: Post, img: Image, post_vec, threshold=None) -> dict:
    t: ImageTag = img.tags
    img_vec = _vec(db, "image", img.id)
    sim = cosine(post_vec, img_vec) if (post_vec and img_vec) else 0.0
    ps, isv = _vec(db, "subject", post.subject), _vec(db, "subject", t.subject)
    subj_sim = cosine(ps, isv) if (ps and isv) else None
    v = guard.check(post_subject=post.subject, post_category=post.category, image_subject=t.subject,
                    image_category=t.category, confidence=t.confidence, flagged=t.flagged,
                    similarity=sim, subject_sim=subj_sim, threshold=threshold)
    return {"image_id": img.id, "filename": img.filename, "subject": t.subject, "caption": t.caption,
            "confidence": round(t.confidence, 3), "similarity": round(sim, 4),
            "verdict": "accepted" if v.accepted else "rejected", "reasons": v.reasons}


def rank_for_post(db, post: Post, limit: int = 5, persist: bool = True, threshold=None) -> dict:
    post_vec = _vec(db, "post", post.id)
    if post.status != "ready" or not post_vec:
        return {"post_id": post.id, "decision": "not_ready", "reasons": ["post has not been processed yet"], "candidates": []}
    imgs = db.scalars(select(Image).where(Image.tenant_id == post.tenant_id, Image.status.in_(["tagged", "flagged"]))).all()
    rows = sorted((evaluate_pair(db, post, i, post_vec, threshold) for i in imgs if i.tags),
                  key=lambda r: r["similarity"], reverse=True)
    for n, r in enumerate(rows, 1):
        r["rank"] = n
    accepted = [r for r in rows if r["verdict"] == "accepted"]
    top = rows[:limit]
    if persist:
        for r in top + accepted[:1]:
            s = db.scalar(select(Suggestion).where(Suggestion.post_id == post.id, Suggestion.image_id == r["image_id"]))
            if s is None:
                s = Suggestion(post_id=post.id, image_id=r["image_id"])
                db.add(s)
            s.rank, s.similarity, s.verdict, s.reasons = r["rank"], r["similarity"], r["verdict"], r["reasons"]
            db.flush()
            r["suggestion_id"] = s.id
        db.commit()
    if accepted:
        return {"post_id": post.id, "post_subject": post.subject, "decision": "match", "best": accepted[0],
                "candidates": top}
    reasons = [f"No image cleared the guard ({len(rows)} checked)."]
    if rows:
        reasons.append(f"Best candidate #{rows[0]['image_id']} ({rows[0]['subject']}): " + "; ".join(rows[0]["reasons"]))
    return {"post_id": post.id, "post_subject": post.subject, "decision": "no_confident_match", "best": None,
            "reasons": reasons, "candidates": top}
