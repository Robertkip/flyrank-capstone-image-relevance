"""Measure top-1 precision on the labelled eval set, and sweep the similarity threshold.
Usage: python -m scripts.eval [--sweep]   Writes eval_results.json."""
import json
import os
import sys
from sqlalchemy import select
from app.config import settings
from app.db import Image, Post, SessionLocal
from app.matching import rank_for_post
from app.taxonomy import canonical


def truth_labels():
    m = json.load(open(os.path.join(settings.images_dir, "manifest.json")))["images"]
    return {x["filename"]: canonical(x["label"]) for x in m}


def run(db, threshold=None, verbose=False):
    labels = truth_labels()
    items = json.load(open("data/eval.json"))["items"]
    rows, correct_match, n_match, correct_refuse, n_refuse = [], 0, 0, 0, 0
    for it in items:
        post = db.scalar(select(Post).where(Post.slug == it["slug"]))
        if post is None:
            continue
        res = rank_for_post(db, post, limit=3, persist=False, threshold=threshold)
        best = res.get("best")
        got = labels.get(best["filename"]) if best else None
        exp = it["expected_subject"]
        ok = (got == exp) if exp else (res["decision"] == "no_confident_match")
        if exp:
            n_match += 1
            correct_match += ok
        else:
            n_refuse += 1
            correct_refuse += ok
        rows.append({"slug": it["slug"], "expected": exp, "decision": res["decision"], "top1_label": got,
                     "top1_similarity": best["similarity"] if best else None, "correct": ok})
        if verbose:
            print(f"{'OK ' if ok else 'XX '} {it['slug']:26s} expected={str(exp):6s} got={str(got):6s} {res['decision']}")
    return {"threshold": threshold or settings.similarity_threshold,
            "top1_precision": round(correct_match / n_match, 3) if n_match else None,
            "top1_correct": correct_match, "posts_with_answer": n_match,
            "refusal_accuracy": round(correct_refuse / n_refuse, 3) if n_refuse else None,
            "refusals_correct": correct_refuse, "posts_without_answer": n_refuse, "rows": rows}


def main():
    db = SessionLocal()
    res = run(db, verbose=True)
    print(f"\nTop-1 precision: {res['top1_correct']}/{res['posts_with_answer']} = {res['top1_precision']}"
          f"   |   correct 'no confident match': {res['refusals_correct']}/{res['posts_without_answer']}"
          f"   (threshold {res['threshold']}, provider {settings.ai_provider})")
    out = {"provider": settings.ai_provider, "vision_model": settings.vision_model, **res}
    if "--sweep" in sys.argv:
        print("\nthreshold  top1_precision  refusal_accuracy")
        out["sweep"] = []
        for th in [x / 100 for x in range(10, 91, 5)]:
            r = run(db, threshold=th)
            out["sweep"].append({k: r[k] for k in ("threshold", "top1_precision", "refusal_accuracy")})
            print(f"  {th:.2f}       {r['top1_precision']}            {r['refusal_accuracy']}")
    json.dump(out, open("eval_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
