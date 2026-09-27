"""HTTP layer. Thin: validates input, calls the logic/data layers, returns JSON. Bad input -> 4xx, never 500."""
import html
import logging
import re
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from .config import settings
from .db import CostLog, Image, Job, Post, Review, SessionLocal, Suggestion
from .migrations import migrate
from .schemas import IngestIn, PostIn, ReviewIn
from . import costs, jobs, matching

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = FastAPI(title="AI Image Understanding & Content Matching Engine", version="1.0.0")
migrate()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def tenant(x_tenant_id: str = Header(default="demo")) -> str:
    if not re.fullmatch(r"[a-z0-9-]{2,40}", x_tenant_id):
        raise HTTPException(400, "X-Tenant-Id must be 2-40 chars of a-z, 0-9, -")
    return x_tenant_id


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logging.getLogger("api").exception("unhandled error")
    return JSONResponse(status_code=500, content={"error": "internal error"})


def job_out(j: Job) -> dict:
    return {"id": j.id, "kind": j.kind, "status": j.status, "total": j.total, "processed": j.processed,
            "flagged": j.flagged, "failed": j.failed, "errors": j.errors[-10:],
            "created_at": j.created_at, "finished_at": j.finished_at}


@app.get("/health")
def health():
    return {"ok": True, "provider": settings.ai_provider}


# ---------- jobs ----------
def _start_job(db, t, kind, idem, fn, *args):
    if idem:
        existing = db.scalar(select(Job).where(Job.tenant_id == t, Job.kind == kind, Job.idempotency_key == idem))
        if existing:
            return JSONResponse(status_code=200, content={"idempotent_replay": True, **_ser(job_out(existing))})
    job = Job(tenant_id=t, kind=kind, idempotency_key=idem, errors=[])
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "job with this Idempotency-Key already exists")
    jobs.submit(fn, job.id, *args)
    return JSONResponse(status_code=202, content=_ser(job_out(job)))


def _ser(d):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}


@app.post("/jobs/ingest-images", status_code=202)
def ingest_images(body: IngestIn = IngestIn(), t: str = Depends(tenant), db=Depends(get_db),
                  idempotency_key: str | None = Header(default=None, max_length=100)):
    return _start_job(db, t, "ingest_images", idempotency_key, jobs.run_image_job, body.force, body.limit)


@app.post("/jobs/process-posts", status_code=202)
def process_posts(body: IngestIn = IngestIn(), t: str = Depends(tenant), db=Depends(get_db),
                  idempotency_key: str | None = Header(default=None, max_length=100)):
    return _start_job(db, t, "process_posts", idempotency_key, jobs.run_post_job, body.force)


@app.get("/jobs/{job_id}")
def get_job(job_id: int, t: str = Depends(tenant), db=Depends(get_db)):
    j = db.get(Job, job_id)
    if not j or j.tenant_id != t:
        raise HTTPException(404, "job not found")
    return job_out(j)


# ---------- images ----------
def image_out(i: Image) -> dict:
    t = i.tags
    return {"id": i.id, "filename": i.filename, "status": i.status, "license": i.license, "source_url": i.source_url,
            "tags": None if not t else {"subject": t.subject, "category": t.category, "attributes": t.attributes,
                                        "caption": t.caption, "confidence": t.confidence, "flagged": t.flagged,
                                        "flag_reason": t.flag_reason, "model": t.model}}


@app.get("/images")
def list_images(status: str | None = Query(default=None, pattern="^(pending|tagged|flagged|failed)$"),
                t: str = Depends(tenant), db=Depends(get_db)):
    q = select(Image).where(Image.tenant_id == t)
    if status:
        q = q.where(Image.status == status)
    return [image_out(i) for i in db.scalars(q.order_by(Image.id)).all()]


@app.get("/images/{image_id}")
def get_image(image_id: int, t: str = Depends(tenant), db=Depends(get_db)):
    i = db.get(Image, image_id)
    if not i or i.tenant_id != t:
        raise HTTPException(404, "image not found")
    return image_out(i)


# ---------- posts & matching ----------
def post_out(p: Post) -> dict:
    return {"id": p.id, "slug": p.slug, "title": p.title, "status": p.status, "subject": p.subject, "category": p.category}


@app.post("/posts", status_code=201)
def create_post(body: PostIn, t: str = Depends(tenant), db=Depends(get_db)):
    slug = body.slug or re.sub(r"[^a-z0-9]+", "-", body.title.lower()).strip("-")[:80]
    existing = db.scalar(select(Post).where(Post.tenant_id == t, Post.slug == slug))
    if existing:   # idempotent create by slug
        return JSONResponse(status_code=200, content=post_out(existing))
    p = Post(tenant_id=t, slug=slug, title=body.title, body=body.body)
    db.add(p)
    db.commit()
    return {**post_out(p), "next": "POST /jobs/process-posts to analyse and embed pending posts"}


@app.get("/posts")
def list_posts(t: str = Depends(tenant), db=Depends(get_db)):
    return [post_out(p) for p in db.scalars(select(Post).where(Post.tenant_id == t).order_by(Post.id)).all()]


def _post(db, t, post_id) -> Post:
    p = db.get(Post, post_id)
    if not p or p.tenant_id != t:
        raise HTTPException(404, "post not found")
    return p


@app.get("/posts/{post_id}/images")
def post_images(post_id: int, limit: int = Query(default=5, ge=1, le=50), t: str = Depends(tenant), db=Depends(get_db)):
    return matching.rank_for_post(db, _post(db, t, post_id), limit=limit)


@app.get("/posts/{post_id}/images/{image_id}/check")
def check_pair(post_id: int, image_id: int, t: str = Depends(tenant), db=Depends(get_db)):
    """Force a specific image as the candidate for a post and see the guard's verdict + reasons."""
    p = _post(db, t, post_id)
    i = db.get(Image, image_id)
    if not i or i.tenant_id != t:
        raise HTTPException(404, "image not found")
    if not i.tags or p.status != "ready":
        raise HTTPException(409, "post or image has not been processed yet")
    vec = matching._vec(db, "post", p.id)
    return {"post": post_out(p), **matching.evaluate_pair(db, p, i, vec)}


# ---------- review ----------
def sugg_out(db, s: Suggestion) -> dict:
    reviews = db.scalars(select(Review).where(Review.suggestion_id == s.id).order_by(Review.id)).all()
    return {"id": s.id, "post_id": s.post_id, "image_id": s.image_id, "rank": s.rank, "similarity": s.similarity,
            "verdict": s.verdict, "why": s.reasons, "review_status": s.review_status,
            "reviews": [{"decision": r.decision, "reviewer": r.reviewer, "note": r.note, "at": r.created_at} for r in reviews]}


@app.get("/suggestions")
def list_suggestions(post_id: int | None = None,
                     review_status: str | None = Query(default=None, pattern="^(pending|approved|rejected)$"),
                     t: str = Depends(tenant), db=Depends(get_db)):
    q = select(Suggestion).join(Post).where(Post.tenant_id == t)
    if post_id:
        q = q.where(Suggestion.post_id == post_id)
    if review_status:
        q = q.where(Suggestion.review_status == review_status)
    return [sugg_out(db, s) for s in db.scalars(q.order_by(Suggestion.post_id, Suggestion.rank)).all()]


def _sugg(db, t, sid) -> Suggestion:
    s = db.get(Suggestion, sid)
    if not s or db.get(Post, s.post_id).tenant_id != t:
        raise HTTPException(404, "suggestion not found")
    return s


@app.get("/suggestions/{sid}")
def inspect_suggestion(sid: int, t: str = Depends(tenant), db=Depends(get_db)):
    """Inspect why an image was selected or refused."""
    s = _sugg(db, t, sid)
    img = db.get(Image, s.image_id)
    return {**sugg_out(db, s), "image": image_out(img), "post": post_out(db.get(Post, s.post_id))}


@app.post("/suggestions/{sid}/review")
def review(sid: int, body: ReviewIn, t: str = Depends(tenant), db=Depends(get_db)):
    s = _sugg(db, t, sid)
    target = "approved" if body.decision == "approve" else "rejected"
    if s.review_status == target:     # idempotent: repeating the same decision does not add a second review
        return {**sugg_out(db, s), "idempotent_replay": True}
    if body.decision == "approve" and s.verdict == "rejected" and not body.note:
        raise HTTPException(422, "approving a guard-rejected pairing requires a note explaining the override")
    db.add(Review(suggestion_id=s.id, decision=body.decision, reviewer=body.reviewer, note=body.note))
    s.review_status = target
    db.commit()
    return sugg_out(db, s)


@app.get("/review", response_class=HTMLResponse)
def review_table(t: str = Depends(tenant), db=Depends(get_db)):
    """Minimal internal review table (no frontend build)."""
    rows = []
    for s in db.scalars(select(Suggestion).join(Post).where(Post.tenant_id == t).order_by(Suggestion.post_id, Suggestion.rank)).all():
        p, i = db.get(Post, s.post_id), db.get(Image, s.image_id)
        color = "#e6f4ea" if s.verdict == "accepted" else "#fdecea"
        rows.append(f"<tr style='background:{color}'><td>{s.id}</td><td>{html.escape(p.title)}</td><td>{html.escape(i.filename)}"
                    f"<br><small>{html.escape(i.tags.subject if i.tags else '')}</small></td><td>{s.rank}</td><td>{s.similarity:.3f}</td>"
                    f"<td><b>{s.verdict}</b><br><small>{html.escape('; '.join(s.reasons))}</small></td><td>{s.review_status}</td></tr>")
    return ("<html><head><title>Review</title><style>body{font-family:system-ui;margin:24px}td,th{border:1px solid #ddd;"
            "padding:6px;font-size:13px;vertical-align:top}table{border-collapse:collapse}</style></head><body>"
            "<h2>Suggested pairings</h2><p>Approve/reject via <code>POST /suggestions/{id}/review</code>.</p><table>"
            "<tr><th>ID</th><th>Post</th><th>Image</th><th>Rank</th><th>Similarity</th><th>Guard</th><th>Review</th></tr>"
            + "".join(rows) + "</table></body></html>")


# ---------- costs ----------
@app.get("/costs")
def cost_report(limit: int = Query(default=50, ge=1, le=1000), db=Depends(get_db)):
    by_kind = db.execute(select(CostLog.kind, func.count(), func.sum(CostLog.input_tokens), func.sum(CostLog.output_tokens),
                                func.sum(CostLog.est_cost_usd)).group_by(CostLog.kind)).all()
    recent = db.scalars(select(CostLog).order_by(CostLog.id.desc()).limit(limit)).all()
    return {"budget_usd": settings.budget_usd, "spent_est_usd": round(costs.total_spent(db), 6),
            "note": "Estimated at paid list prices; on the Gemini free tier the actual charge is $0.",
            "by_kind": [{"kind": k, "calls": c, "input_tokens": i or 0, "output_tokens": o or 0, "est_usd": round(u or 0, 6)}
                        for k, c, i, o, u in by_kind],
            "calls": [{"id": c.id, "job_id": c.job_id, "kind": c.kind, "model": c.model, "target": c.target, "ok": c.ok,
                       "attempt": c.attempt, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens,
                       "est_usd": c.est_cost_usd} for c in recent]}
