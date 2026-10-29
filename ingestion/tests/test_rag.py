"""Offline tests for settings, chunking, write protection and ingest failure handling.
Live gateway/Qdrant behaviour is verified separately (see ingestion/README.md)."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402
import ingest  # noqa: E402
import rag  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings_file(tmp_path):
    def write(**overrides):
        settings = yaml.safe_load((ROOT / "rag-settings.yaml").read_text())
        settings.update(overrides)
        path = tmp_path / "rag-settings.yaml"
        path.write_text(yaml.safe_dump({k: v for k, v in settings.items() if v is not None}))
        return path
    return write


def test_versioned_settings_are_valid():
    settings = rag.load_settings(ROOT / "rag-settings.yaml")
    assert settings["embedding_model"] == "course-embed"
    assert settings["collection_prefix"] == "study_guides"
    assert settings["top_k"] == 3


@pytest.mark.parametrize("override, message", [
    ({"chunk_size": 5}, "chunk_size"),
    ({"chunk_overlap": 900}, "chunk_overlap"),
    ({"top_k": 0}, "top_k"),
    ({"top_k": True}, "top_k"),
    ({"embedding_model": ""}, "embedding_model"),
    ({"collection_prefix": "Study Guides"}, "collection_prefix"),
    ({"rerank": True}, "unknown keys"),
    ({"top_k": None}, "missing keys"),
])
def test_bad_settings_fail(settings_file, override, message):
    with pytest.raises(rag.RagError, match=message):
        rag.load_settings(settings_file(**override))


def test_chunks_respect_size_keep_headings_and_cover_the_text():
    documents = corpus.select_corpus("docs/study-guides", root=ROOT)
    for doc in documents:
        chunks = rag.chunk_document(doc, 800, 120)
        _, body = rag.split_front_matter(doc.text)
        assert all(len(c.text) <= 800 for c in chunks), doc.path
        assert all(c.text.startswith(c.title) for c in chunks)
        assert [c.index for c in chunks] == list(range(len(chunks)))
        assert "source_revision" not in " ".join(c.text for c in chunks)  # front matter not embedded
        joined = " ".join(" ".join(c.text.split()) for c in chunks)
        for sentence in body.split(". ")[:20]:  # every sampled sentence survives chunking
            words = " ".join(sentence.split()[:6])
            if words and not words.startswith("#"):
                assert words in joined, (doc.path, words)


def test_overlap_repeats_trailing_text_within_a_section():
    text = " ".join(f"Sentence number {n} talks about Kubernetes probes." for n in range(40))
    doc = corpus.Document("docs/x.md", f"---\ntitle: X\n---\n# X\n\n## S\n\n{text}\n", "0")
    chunks = rag.chunk_document(doc, 400, 100)
    assert len(chunks) > 2
    for prev, nxt in zip(chunks, chunks[1:]):
        tail = prev.text.split("\n\n", 1)[1][-40:]
        assert tail.split()[-1] in nxt.text


class FakeQdrant:
    def __init__(self, aliases=None, fail_upsert=False):
        self._aliases, self.fail_upsert = aliases or {}, fail_upsert
        self.collections, self.deleted, self.writes = {}, [], 0

    def aliases(self):
        return dict(self._aliases)

    def exists(self, name):
        return name in self.collections

    def sample_payload(self, name):
        points = self.collections.get(name) or []
        return points[0]["payload"] if points else {}

    def recreate(self, name, dimension):
        self.writes += 1
        self.collections[name] = []

    def upsert(self, name, points):
        self.collections[name] += points[:64]
        if self.fail_upsert:
            raise rag.RagError("Qdrant PUT /points: HTTP 500 simulated crash after first batch")
        self.collections[name] += points[64:]

    def count(self, name):
        return len(self.collections[name])

    def delete(self, name):
        self.deleted.append(name)
        self.collections.pop(name)


@pytest.mark.parametrize("name, message", [
    ("study_guides", "LIVE alias"),
    ("monitoring_demo", "protected fixture"),
    ("other", "must be named study_guides_"),
    ("study_guides_x y", "invalid collection name"),
])
def test_protected_collections_are_refused(name, message):
    fake = FakeQdrant(aliases={"study_guides": "study_guides_live"})
    with pytest.raises(rag.RagError, match=message):
        rag.check_writable(fake, name, "study_guides")


def test_candidate_states():
    fake = FakeQdrant(aliases={"study_guides": "study_guides_live"})
    fake.collections["study_guides_old"] = [{"payload": {}}]
    assert rag.check_writable(fake, "study_guides_manual", "study_guides") == "new"
    assert rag.check_writable(fake, "study_guides_old", "study_guides") == "exists"
    assert rag.check_writable(fake, "study_guides_live", "study_guides") == "live"


@pytest.fixture
def offline(monkeypatch):
    """Run ingest.main from the repo root against fakes."""
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("COURSE_VIRTUAL_KEY", "sk-test-not-real")
    fake = FakeQdrant()
    monkeypatch.setattr(rag, "Qdrant", lambda: fake)
    return fake


def run(argv=("--docs", "docs/study-guides", "--collection", "study_guides_test")):
    return ingest.main(list(argv))


def test_ingest_success_records_provenance(offline, monkeypatch, capsys):
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[0.1] * 4096 for _ in texts])
    assert run() == 0
    points = offline.collections["study_guides_test"]
    payload = points[0]["payload"]
    assert payload["corpus_chunks"] == len(points)
    assert payload["embedding_model"] == "course-embed"
    assert payload["source"].startswith("docs/study-guides/") and payload["citation"].startswith(payload["source"])
    assert len(payload["corpus_hash"]) == 64 and payload["text"]
    out = capsys.readouterr().out
    assert "COMPLETE candidate 'study_guides_test'" in out
    assert "sk-test-not-real" not in str(points) + out


def test_gateway_failure_writes_nothing(offline, monkeypatch):
    def boom(*a):
        raise rag.RagError("gateway HTTP 429: Budget has been exceeded")
    monkeypatch.setattr(rag, "embed", boom)
    assert run() == 1
    assert offline.collections == {}


def test_dimension_mismatch_writes_nothing(offline, monkeypatch, capsys):
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[0.1] * 1024 for _ in texts])
    assert run() == 1
    assert offline.collections == {}
    assert "dimension 1024" in capsys.readouterr().err


def test_mid_upsert_failure_removes_partial_candidate(offline, monkeypatch, capsys):
    offline.fail_upsert = True
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[0.1] * 4096 for _ in texts])
    assert run() == 1
    assert offline.deleted == ["study_guides_test"] and offline.collections == {}
    err = capsys.readouterr()
    assert "removed partial collection" in err.err and "COMPLETE" not in err.out


def test_partial_candidate_is_reported_when_cleanup_also_fails(offline, monkeypatch, capsys):
    offline.fail_upsert = True
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[0.1] * 4096 for _ in texts])

    def cannot_delete(name):
        raise rag.RagError("Qdrant unreachable")
    offline.delete = cannot_delete
    assert run() == 1
    assert "is NOT a complete candidate" in capsys.readouterr().err


# ---------------------------------------------------------------- RAG-03 retry policy

SHA = "a" * 40


def ingest_release(fake, monkeypatch, settings=None, collection=f"study_guides_{SHA}"):
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[0.1] * 4096 for _ in texts])
    argv = ["--docs", "docs/study-guides", "--collection", collection, "--revision", SHA]
    return ingest.main(argv + (["--settings", str(settings)] if settings else []))


def test_identical_unpromoted_candidate_is_recreated_with_same_provenance(offline, monkeypatch):
    assert ingest_release(offline, monkeypatch) == 0
    first = [p["payload"] for p in offline.collections[f"study_guides_{SHA}"]]
    assert ingest_release(offline, monkeypatch) == 0
    second = [p["payload"] for p in offline.collections[f"study_guides_{SHA}"]]
    assert first == second and offline.writes == 2


def test_live_candidate_with_matching_provenance_is_reused_untouched(offline, monkeypatch, capsys):
    assert ingest_release(offline, monkeypatch) == 0
    offline._aliases = {"study_guides": f"study_guides_{SHA}"}
    before = list(offline.collections[f"study_guides_{SHA}"])
    monkeypatch.setattr(rag, "embed", lambda *a: pytest.fail("a reused live candidate must not call the gateway"))
    assert ingest.main(["--docs", "docs/study-guides", "--collection", f"study_guides_{SHA}", "--revision", SHA]) == 0
    assert offline.collections[f"study_guides_{SHA}"] == before and offline.writes == 1
    assert "REUSED live candidate" in capsys.readouterr().out


def test_live_candidate_with_different_provenance_fails_for_recovery(offline, monkeypatch, capsys):
    assert ingest_release(offline, monkeypatch) == 0
    offline._aliases = {"study_guides": f"study_guides_{SHA}"}
    for point in offline.collections[f"study_guides_{SHA}"]:
        point["payload"]["corpus_hash"] = "tampered"
    before = [dict(p["payload"]) for p in offline.collections[f"study_guides_{SHA}"]]
    assert ingest_release(offline, monkeypatch) == 1
    assert [p["payload"] for p in offline.collections[f"study_guides_{SHA}"]] == before
    assert offline.aliases() == {"study_guides": f"study_guides_{SHA}"} and offline.writes == 1
    err = capsys.readouterr().err
    assert "is LIVE and its stored provenance differs" in err and "corpus_hash" in err


def test_changed_settings_under_the_same_release_identity_are_rejected(offline, monkeypatch, tmp_path, capsys):
    assert ingest_release(offline, monkeypatch) == 0
    changed = tmp_path / "rag-settings.yaml"
    changed.write_text((ROOT / "rag-settings.yaml").read_text().replace("chunk_size: 800", "chunk_size: 600"))
    assert ingest_release(offline, monkeypatch, settings=changed) == 1
    assert offline.writes == 1
    assert "DIFFERENT inputs" in capsys.readouterr().err


# ---------------------------------------------------------------- gateway batching bug (found in the S12 CD run)

def test_embed_sends_one_text_per_request_and_keeps_order(monkeypatch):
    """Batched requests came back misordered on the course gateway when some inputs were cached."""
    seen = []

    class Resp:
        status_code = 200
        def __init__(self, text): self._text = text
        def json(self): return {"data": [{"index": 0, "embedding": [float(len(self._text)), 1.0]}]}

    def fake_post(client, url, body, key):
        assert len(body["input"]) == 1, "embeddings must be requested one text at a time"
        seen.append(body["input"][0])
        return Resp(body["input"][0])

    monkeypatch.setattr(rag, "_post_with_retry", fake_post)
    texts = ["a", "bb", "ccc", "dddd", "eeeee"]
    vectors = rag.embed(texts, "course-embed", "http://gw", "sk-test")
    assert sorted(seen) == sorted(texts)
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_spot_check_rejects_misaligned_vectors(monkeypatch):
    monkeypatch.setattr(rag, "embed", lambda texts, *a: [[1.0, 0.0] if texts[0] == "a" else [0.0, 1.0]])
    rag.spot_check(["a", "b"], [[1.0, 0.0], [0.0, 1.0]], "m", "g", "k")          # aligned: passes
    with pytest.raises(rag.RagError, match="inconsistent embedding"):
        rag.spot_check(["a", "b"], [[0.0, 1.0], [1.0, 0.0]], "m", "g", "k")      # swapped: refused


def test_rate_limit_is_retried_but_budget_is_not(monkeypatch):
    monkeypatch.setattr(rag.time, "sleep", lambda s: None)
    class R:
        def __init__(self, code, text=""): self.status_code, self.text, self.headers = code, text, {}
    calls = []
    class Client:
        def __init__(self, replies): self.replies = replies
        def post(self, *a, **k): calls.append(1); return self.replies.pop(0)
    ok = rag._post_with_retry(Client([R(429, "Rate limit exceeded"), R(429, "Rate limit exceeded"), R(200)]), "u", {}, "k")
    assert ok.status_code == 200 and len(calls) == 3
    calls.clear()
    budget = rag._post_with_retry(Client([R(429, "Budget has been exceeded!")]), "u", {}, "k")
    assert budget.status_code == 429 and len(calls) == 1


def test_qualification_stops_at_first_429_without_queue_or_retry(monkeypatch):
    import httpx
    monkeypatch.setenv("RAG_QUALIFICATION_BUDGET", "4")
    monkeypatch.setenv("RAG_QUALIFICATION_INTERVAL_SECONDS", "2.1")
    monkeypatch.setattr(rag, "_qualification_requests", 0)
    monkeypatch.setattr(rag, "_qualification_next_request", 0)
    calls = []
    def post(self, *args, **kwargs):
        calls.append(1)
        return httpx.Response(429, text="rate limited")
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(rag.RagError, match="HTTP 429"):
        rag.embed(["one", "two", "three"], "course-embed", "https://fixture.invalid", "private")
    assert len(calls) == 1


def test_qualification_budget_and_pacing(monkeypatch):
    import httpx
    monkeypatch.setenv("RAG_QUALIFICATION_BUDGET", "2")
    monkeypatch.setenv("RAG_QUALIFICATION_INTERVAL_SECONDS", "13")
    monkeypatch.setattr(rag, "_qualification_requests", 0)
    monkeypatch.setattr(rag, "_qualification_next_request", 0)
    now = [100.0]
    starts = []
    monkeypatch.setattr(rag.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(rag.time, "sleep", lambda n: now.__setitem__(0, now[0]+n))
    def post(self, *args, **kwargs):
        starts.append(now[0])
        return httpx.Response(200, json={"data": [{"embedding": [1.0]}]})
    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(rag.RagError, match="budget exhausted"):
        rag.embed(["one", "two", "three"], "course-embed", "https://fixture.invalid", "private")
    assert starts == [100.0, 113.0]
