import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.update({"AI_PROVIDER": "mock", "DATABASE_URL": f"sqlite:///{_tmp}/test.db",
                   "IMAGES_DIR": f"{_tmp}/images", "ALERT_LOG": f"{_tmp}/alerts.log", "AI_BUDGET_USD": "5",
                   "SIMILARITY_THRESHOLD": "0.25"})  # mock bag-of-words vectors use a different similarity scale
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scripts.make_mock_corpus import PLAN  # noqa
import subprocess  # noqa
subprocess.run([sys.executable, "-m", "scripts.make_mock_corpus", f"{_tmp}/images"], check=True,
               cwd=os.path.dirname(os.path.dirname(__file__)), capture_output=True)

import json  # noqa
import pytest  # noqa
from fastapi.testclient import TestClient  # noqa
from app.main import app  # noqa
from app.db import Job, Post, SessionLocal  # noqa
from app import jobs  # noqa


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def seeded(client):
    """Create the demo posts and run both batch jobs synchronously (same code the worker runs)."""
    db = SessionLocal()
    root = os.path.dirname(os.path.dirname(__file__))
    for p in json.load(open(os.path.join(root, "data/posts.json")))["posts"]:
        client.post("/posts", json={"title": p["title"], "body": p["body"], "slug": p["slug"]})
    for kind, fn in (("ingest_images", jobs.run_image_job), ("process_posts", jobs.run_post_job)):
        j = Job(tenant_id="demo", kind=kind, errors=[])
        db.add(j)
        db.commit()
        fn(j.id)
    return {p.slug: p.id for p in db.query(Post).all()}
