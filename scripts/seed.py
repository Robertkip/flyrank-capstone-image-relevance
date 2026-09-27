"""Seed step: register images, create the demo posts, and run both batch jobs to completion.
Usage: python -m scripts.seed   (idempotent - safe to run twice)"""
import json
import os
import time
from sqlalchemy import select
from app.db import Job, Post, SessionLocal
from app.migrations import migrate
from app import jobs

TENANT = os.getenv("SEED_TENANT", "demo")


def wait(db, job_id):
    while True:
        db.expire_all()
        j = db.get(Job, job_id)
        if j.status not in ("queued", "running"):
            return j
        print(f"  job {j.id} {j.kind}: {j.processed}/{j.total} (flagged {j.flagged}, failed {j.failed})")
        time.sleep(2)


def main():
    migrate()
    db = SessionLocal()
    for p in json.load(open("data/posts.json"))["posts"]:
        if not db.scalar(select(Post).where(Post.tenant_id == TENANT, Post.slug == p["slug"])):
            db.add(Post(tenant_id=TENANT, slug=p["slug"], title=p["title"], body=p["body"]))
    db.commit()
    for kind, fn in (("ingest_images", jobs.run_image_job), ("process_posts", jobs.run_post_job)):
        job = Job(tenant_id=TENANT, kind=kind, errors=[])
        db.add(job)
        db.commit()
        jobs.submit(fn, job.id)
        j = wait(db, job.id)
        print(f"{kind}: status={j.status} processed={j.processed}/{j.total} flagged={j.flagged} failed={j.failed}")
        for e in j.errors[-5:]:
            print("   error:", e)
    jobs.executor.shutdown(wait=True)


if __name__ == "__main__":
    main()
