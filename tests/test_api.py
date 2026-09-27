"""Boundary validation, idempotency, review workflow, tenant isolation."""


def test_bad_input_is_4xx_not_500(client, seeded):
    assert client.post("/posts", json={"title": "x", "body": "short"}).status_code == 422
    assert client.get("/posts/999999/images").status_code == 404
    assert client.get("/images?status=bogus").status_code == 422
    assert client.get("/images", headers={"X-Tenant-Id": "BAD TENANT!"}).status_code == 400
    assert client.post("/suggestions/1/review", json={"decision": "maybe", "reviewer": "me"}).status_code == 422


def test_create_post_is_idempotent_by_slug(client, seeded):
    body = {"title": "The behavior of red foxes", "body": "x" * 30, "slug": "red-fox-behavior"}
    r = client.post("/posts", json=body)
    assert r.status_code == 200 and r.json()["id"] == seeded["red-fox-behavior"]


def test_review_approve_is_idempotent_and_inspectable(client, seeded):
    best = client.get(f"/posts/{seeded['red-fox-behavior']}/images").json()["best"]
    sid = best["suggestion_id"]
    r1 = client.post(f"/suggestions/{sid}/review", json={"decision": "approve", "reviewer": "robert"})
    r2 = client.post(f"/suggestions/{sid}/review", json={"decision": "approve", "reviewer": "robert"})
    assert r1.json()["review_status"] == "approved" and r2.json()["idempotent_replay"] is True
    info = client.get(f"/suggestions/{sid}").json()
    assert len(info["reviews"]) == 1 and info["why"][0].startswith("subject match")


def test_overriding_a_guard_rejection_requires_a_note(client, seeded):
    r = client.get(f"/posts/{seeded['red-fox-behavior']}/images?limit=46").json()
    rejected = next(c for c in r["candidates"] if c["verdict"] == "rejected" and "suggestion_id" in c)
    resp = client.post(f"/suggestions/{rejected['suggestion_id']}/review", json={"decision": "approve", "reviewer": "robert"})
    assert resp.status_code == 422


def test_tenants_are_isolated(client, seeded):
    assert client.get("/images", headers={"X-Tenant-Id": "other-co"}).json() == []
    assert client.get(f"/posts/{seeded['red-fox-behavior']}/images", headers={"X-Tenant-Id": "other-co"}).status_code == 404


def test_ingest_job_idempotency_key(client, seeded):
    r1 = client.post("/jobs/ingest-images", json={}, headers={"Idempotency-Key": "abc-123"})
    r2 = client.post("/jobs/ingest-images", json={}, headers={"Idempotency-Key": "abc-123"})
    assert r1.status_code == 202 and r2.status_code == 200 and r2.json()["idempotent_replay"]
    assert r1.json()["id"] == r2.json()["id"]
