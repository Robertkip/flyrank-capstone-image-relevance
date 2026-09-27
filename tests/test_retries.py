"""Retries + cost attribution per attempt + invalid output is never stored."""
from app import jobs
from app.db import CostLog, Image, Job, SessionLocal
from app.providers.base import ProviderError, Usage
from app.schemas import ImageTags


class Flaky:
    def __init__(self, fail_times, invalid=False):
        self.calls, self.fail_times, self.invalid = 0, fail_times, invalid

    def describe_image(self, path):
        self.calls += 1
        if self.invalid:
            raise ProviderError("schema validation failed: missing fields")
        if self.calls <= self.fail_times:
            raise ProviderError("Gemini 503: overloaded")
        return ImageTags(subject="red fox", category="animal", attributes=["x"], caption="A red fox here.", confidence=0.9), Usage("m", 10, 5)


def _job(db):
    j = Job(tenant_id="demo", kind="test", errors=[])
    db.add(j)
    db.commit()
    return j


def test_transient_failure_is_retried_and_each_attempt_costed(seeded):
    db = SessionLocal()
    job, p = _job(db), Flaky(fail_times=2)
    tags = jobs.with_retries(db, job, "vision", "image:test", lambda: p.describe_image("x"))
    db.commit()
    assert tags.subject == "red fox" and p.calls == 3
    rows = db.query(CostLog).filter(CostLog.job_id == job.id).order_by(CostLog.attempt).all()
    assert [(r.attempt, r.ok) for r in rows] == [(1, False), (2, False), (3, True)]


def test_invalid_output_after_retries_raises_and_is_not_stored(seeded):
    db = SessionLocal()
    job, p = _job(db), Flaky(fail_times=0, invalid=True)
    try:
        jobs.with_retries(db, job, "vision", "image:test", lambda: p.describe_image("x"))
        assert False, "should have raised"
    except ProviderError as e:
        assert "schema validation failed" in str(e)
    assert p.calls == 3
