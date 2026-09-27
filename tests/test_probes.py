"""The six acceptance probes from the brief, run end-to-end against the API (mock provider)."""
from app.schemas import ImageTags


def test_probe1_batch_tags_every_image_and_flags_low_confidence(client, seeded):
    imgs = client.get("/images").json()
    assert len(imgs) == 46
    assert all(i["status"] in ("tagged", "flagged") for i in imgs)
    for i in imgs:
        ImageTags(**{k: i["tags"][k] for k in ("subject", "category", "attributes", "caption", "confidence")})
    flagged = [i for i in imgs if i["status"] == "flagged"]
    assert len(flagged) >= 1 and all(i["tags"]["flagged"] and i["tags"]["flag_reason"] for i in flagged)


def test_probe2_fox_post_ranks_fox_first(client, seeded):
    r = client.get(f"/posts/{seeded['red-fox-behavior']}/images?limit=46").json()
    assert r["decision"] == "match" and r["best"]["subject"] == "red fox"
    ranks = {c["subject"]: c["rank"] for c in reversed(r["candidates"])}   # best rank per subject
    assert ranks["red fox"] < ranks["gray wolf"] and ranks["red fox"] < ranks["dog"]
    assert all(c["verdict"] == "rejected" for c in r["candidates"] if c["subject"] in ("gray wolf", "dog"))


def test_probe2b_synonym_post_finds_fox(client, seeded):
    r = client.get(f"/posts/{seeded['vulpes-vulpes-diet']}/images").json()
    assert r["decision"] == "match" and r["best"]["subject"] == "red fox"


def test_probe3_forced_wolf_is_rejected(client, seeded):
    wolf = next(i for i in client.get("/images").json() if i["tags"]["subject"] == "gray wolf")
    r = client.get(f"/posts/{seeded['red-fox-behavior']}/images/{wolf['id']}/check").json()
    assert r["verdict"] == "rejected"
    assert "Animal category mismatch: expected fox, detected wolf" in r["reasons"]


def test_probe4_no_suitable_image(client, seeded):
    r = client.get(f"/posts/{seeded['sourdough-starter']}/images").json()
    assert r["decision"] == "no_confident_match" and r["best"] is None
    assert any("mismatch" in x.lower() or "below threshold" in x for x in r["reasons"][1].split(";"))


def test_probe6_every_ai_call_has_a_cost_entry(client, seeded):
    c = client.get("/costs?limit=1000").json()
    kinds = {k["kind"]: k["calls"] for k in c["by_kind"]}
    assert kinds["vision"] >= 46 and kinds["embedding"] >= 46 + 14 and kinds["text"] >= 14
    assert all(call["target"] and call["model"] for call in c["calls"])
