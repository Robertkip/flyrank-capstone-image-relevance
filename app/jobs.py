"""Background batch jobs: image tagging + embedding, post analysis + embedding.
Runs off the request path in a worker thread, with retries, progress, per-call cost logging,
a budget guard and a failure alert. Idempotent: already-processed items are skipped unless force=True."""
import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from sqlalchemy import select
from .config import settings
from .db import Embedding, Image, ImageTag, Job, Post, SessionLocal
from . import costs
from .providers import get_provider
from .providers.base import ProviderError

log = logging.getLogger("jobs")
executor = ThreadPoolExecutor(max_workers=1)      # one worker = predictable free-tier rate usage
ALERT_FILE = os.getenv("ALERT_LOG", "./data/alerts.log")


def alert(job: Job, msg: str):
    """Failure alert: logged at ERROR and appended to data/alerts.log (swap for email/Slack in production)."""
    line = f"{datetime.now(timezone.utc).isoformat()} job={job.id} kind={job.kind} {msg}"
    log.error("ALERT %s", line)
    os.makedirs(os.path.dirname(ALERT_FILE), exist_ok=True)
    with open(ALERT_FILE, "a") as f:
        f.write(line + "\n")


def with_retries(db, job, kind, target, fn):
    """Call fn() up to MAX_RETRIES times with exponential backoff. Every attempt is cost-logged."""
    last = None
    for attempt in range(1, settings.max_retries + 1):
        if costs.over_budget(db):
            raise ProviderError(f"budget guard: spent >= ${settings.budget_usd}", retryable=False)
        try:
            result, usage = fn()
            costs.record(db, job_id=job.id, kind=kind, target=target, usage=usage, ok=True, attempt=attempt)
            return result
        except ProviderError as e:
            last = e
            costs.record(db, job_id=job.id, kind=kind, target=target, usage=None, ok=False, attempt=attempt,
                         model=settings.vision_model if kind != "embedding" else settings.embedding_model)
            if not e.retryable:
                break
            if settings.ai_provider != "mock":
                time.sleep(2 ** attempt)
    raise last


def upsert_embedding(db, owner_type, owner_key, model, text, vector):
    e = db.scalar(select(Embedding).where(Embedding.owner_type == owner_type, Embedding.owner_key == str(owner_key),
                                          Embedding.model == model))
    if e is None:
        e = Embedding(owner_type=owner_type, owner_key=str(owner_key), model=model, text=text, vector=vector)
        db.add(e)
    else:
        e.text, e.vector = text, vector


def ensure_subject_vectors(db, provider, job, subjects: set[str]):
    have = set(db.scalars(select(Embedding.owner_key).where(Embedding.owner_type == "subject")).all())
    todo = sorted(s for s in subjects if s and s not in have)
    if todo:
        vecs = with_retries(db, job, "embedding", f"subjects:{len(todo)}", lambda: provider.embed(todo))
        for s, v in zip(todo, vecs):
            upsert_embedding(db, "subject", s, settings.embedding_model, s, v)


def sync_image_files(db, tenant_id: str) -> None:
    """Register image files from IMAGES_DIR (dedup by content hash) with license info from the manifest."""
    manifest = {}
    mpath = os.path.join(settings.images_dir, "manifest.json")
    if os.path.exists(mpath):
        manifest = {m["filename"]: m for m in json.load(open(mpath))["images"]}
    for name in sorted(os.listdir(settings.images_dir)):
        if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        sha = hashlib.sha256(open(os.path.join(settings.images_dir, name), "rb").read()).hexdigest()
        if db.scalar(select(Image.id).where(Image.tenant_id == tenant_id, Image.sha256 == sha)):
            continue
        m = manifest.get(name, {})
        db.add(Image(tenant_id=tenant_id, filename=name, sha256=sha, source_url=m.get("source_url"), license=m.get("license")))
    db.commit()


def run_image_job(job_id: int, force: bool = False, limit: int | None = None):
    db = SessionLocal()
    job = db.get(Job, job_id)
    try:
        provider = get_provider()
        sync_image_files(db, job.tenant_id)
        q = select(Image).where(Image.tenant_id == job.tenant_id)
        if not force:
            q = q.where(Image.status.in_(["pending", "failed"]))
        images = db.scalars(q.order_by(Image.id)).all()[: limit or None]
        job.status, job.total = "running", len(images)
        db.commit()
        for img in images:
            try:
                tags = with_retries(db, job, "vision", f"image:{img.id}",
                                    lambda: provider.describe_image(os.path.join(settings.images_dir, img.filename)))
                flagged = tags.confidence < settings.min_confidence
                t = img.tags or ImageTag(image_id=img.id)
                t.subject, t.category, t.attributes, t.caption, t.confidence = (
                    tags.subject, tags.category, tags.attributes, tags.caption, tags.confidence)
                t.flagged, t.model = flagged, settings.vision_model if settings.ai_provider != "mock" else "mock-vision"
                t.flag_reason = f"confidence {tags.confidence:.2f} < {settings.min_confidence:.2f}" if flagged else None
                if img.tags is None:
                    db.add(t)
                text = f"{tags.subject}. {tags.caption} Attributes: {', '.join(tags.attributes)}."
                vec = with_retries(db, job, "embedding", f"image:{img.id}", lambda: provider.embed([text]))[0]
                upsert_embedding(db, "image", img.id, settings.embedding_model, text, vec)
                img.status = "flagged" if flagged else "tagged"
                job.flagged += int(flagged)
            except ProviderError as e:
                img.status = "failed"
                job.failed += 1
                job.errors = [*job.errors, f"image:{img.id} {img.filename}: {e}"]
                if "budget guard" in str(e):
                    job.status = "budget_stopped"
                    alert(job, str(e))
                    db.commit()
                    return
            job.processed += 1
            db.commit()
        subjects = {t for t in db.scalars(select(ImageTag.subject)).all()}
        ensure_subject_vectors(db, provider, job, subjects)
        finish(db, job)
    except Exception as e:  # never leave a job 'running' forever
        db.rollback()
        job.status, job.errors = "failed", [*job.errors, f"fatal: {e}"]
        alert(job, f"fatal: {e}")
        db.commit()
    finally:
        db.close()


def run_post_job(job_id: int, force: bool = False):
    db = SessionLocal()
    job = db.get(Job, job_id)
    try:
        provider = get_provider()
        q = select(Post).where(Post.tenant_id == job.tenant_id)
        if not force:
            q = q.where(Post.status.in_(["pending", "failed"]))
        posts = db.scalars(q.order_by(Post.id)).all()
        job.status, job.total = "running", len(posts)
        db.commit()
        for p in posts:
            try:
                topic = with_retries(db, job, "text", f"post:{p.id}", lambda: provider.analyze_post(p.title, p.body))
                p.subject, p.category, p.keywords = topic.subject, topic.category, topic.keywords
                text = f"{p.title}\n\n{p.body[:4000]}"
                vec = with_retries(db, job, "embedding", f"post:{p.id}", lambda: provider.embed([text]))[0]
                upsert_embedding(db, "post", p.id, settings.embedding_model, text[:2000], vec)
                p.status = "ready"
            except ProviderError as e:
                p.status, job.failed = "failed", job.failed + 1
                job.errors = [*job.errors, f"post:{p.id}: {e}"]
            job.processed += 1
            db.commit()
        ensure_subject_vectors(db, provider, job, {p.subject for p in posts if p.subject})
        finish(db, job)
    except Exception as e:
        db.rollback()
        job.status, job.errors = "failed", [*job.errors, f"fatal: {e}"]
        alert(job, f"fatal: {e}")
        db.commit()
    finally:
        db.close()


def finish(db, job):
    job.status = "done" if job.failed == 0 else "done_with_errors"
    job.finished_at = datetime.now(timezone.utc)
    if job.failed:
        alert(job, f"{job.failed} item(s) failed after retries: {job.errors[-3:]}")
    db.commit()


def submit(fn, *args):
    return executor.submit(fn, *args)
