"""scripts/receipt.py fixtures: passing accepted; failing, missing, stale and tampered rejected."""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import receipt  # noqa: E402

FILES = ["docs/study-guides", "ingestion/corpus.py", "ingestion/ingest.py", "ingestion/rag.py",
         "rag-settings.yaml", "course-artifacts.yaml", ".gitignore"]


@pytest.fixture
def release(tmp_path, monkeypatch):
    """A committed checkout + a state dir holding a PASSING evaluation of its candidate."""
    repo = tmp_path / "wb"
    for rel in FILES:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if (ROOT / rel).is_dir() else shutil.copy2)(ROOT / rel, repo / rel)
    g = ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t"]
    subprocess.run(g + ["init", "-q"], check=True)
    subprocess.run(g + ["add", "-A"], check=True)
    subprocess.run(g + ["commit", "-qm", "base"], check=True)
    sha = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    monkeypatch.chdir(repo)
    ident = receipt.checkout_identity()
    state = tmp_path / "state"
    state.mkdir()
    (state / "bundle-identity.json").write_text(json.dumps({"image": receipt.pinned_image()}))
    results = {
        "candidate": {"collection": f"study_guides_{sha}", "physical": f"study_guides_{sha}", "points": 163,
                      "corpus_hash": ident["corpus_hash"], "corpus_revision": sha, "embedding_model": "course-embed",
                      "settings_hash": ident["settings_hash"], "ingestion_source_hash": ident["ingestion_source_hash"]},
        "query_model": "course-embed", "k": 3, "threshold": 0.8, "required": 8, "hits": 10, "total": 10,
        "score": 1.0, "passed": True, "questions": [],
    }
    (state / "eval-results.json").write_text(json.dumps(results))
    args = argparse.Namespace(state=str(state), sha=sha, manual=None, qdrant_url=None)
    receipt.make(args)
    return repo, state, sha, args


def edit(state, **changes):
    path = state / "receipt.json"
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def test_valid_matching_pass_is_accepted(release):
    _, state, sha, args = release
    r = json.loads((state / "receipt.json").read_text())
    assert r["revision"] == sha and r["candidate"] == f"study_guides_{sha}" and r["passed"] is True
    assert r["image"].startswith("ghcr.io/oriolrius/workbench-ingestion@sha256:")
    assert {"corpus_hash", "ingestion_model", "query_model", "hits", "total", "threshold"} <= set(r)
    assert receipt.verify(args) == []


def test_failed_evaluation_is_rejected(release):
    _, state, _, args = release
    edit(state, hits=2, score=0.2, passed=False)
    reasons = receipt.verify(args)
    assert any("evaluation FAILED" in r for r in reasons)


def test_missing_receipt_is_rejected(release):
    _, state, _, args = release
    (state / "receipt.json").unlink()
    assert "no receipt" in receipt.verify(args)[0]


@pytest.mark.parametrize("changes, reason", [
    ({"hits": 10, "passed": True, "required": 1}, "inconsistent"),            # pass claimed with a wrong requirement
    ({"hits": 2}, "inconsistent"),                                              # hits lowered but still 'passed'
    ({"threshold": 0.1, "required": 1}, "gate weaker"),
    ({"candidate": "study_guides_other"}, "candidate"),
    ({"revision": "f" * 40}, "revision"),
    ({"image": "ghcr.io/oriolrius/workbench-ingestion@sha256:" + "0" * 64}, "image"),
    ({"ingestion_model": "course-embed-decoy"}, "ingestion_model"),
    ({"query_model": "course-embed-decoy"}, "query_model"),
    ({"corpus_hash": "0" * 64}, "corpus_hash"),
    ({"stored_revision": "e" * 40}, "was built from"),
    ({"schema": "something/else"}, "schema"),
])
def test_tampered_receipt_is_rejected(release, changes, reason):
    _, state, _, args = release
    edit(state, **changes)
    reasons = receipt.verify(args)
    assert reasons and any(reason in r for r in reasons), reasons


def test_changed_results_file_is_rejected(release):
    _, state, _, args = release
    (state / "eval-results.json").write_text("{}")
    assert any("eval-results.json" in r for r in receipt.verify(args))


def test_stale_receipt_after_the_corpus_changes_is_rejected(release):
    repo, _, _, args = release
    guide = repo / "docs/study-guides/session-06-terraform-iac.md"
    guide.write_text(guide.read_text() + "\nAn edit after the evaluation.\n")
    reasons = receipt.verify(args)
    assert any("corpus_hash" in r and "stale" in r for r in reasons)


def test_stale_receipt_after_the_settings_change_is_rejected(release):
    repo, _, _, args = release
    settings = repo / "rag-settings.yaml"
    settings.write_text(settings.read_text().replace("embedding_model: course-embed", "embedding_model: course-embed-decoy"))
    reasons = receipt.verify(args)
    assert any("settings_hash" in r for r in reasons) and any("ingestion_model" in r for r in reasons)


def test_receipt_for_another_release_is_rejected(release):
    _, _, _, args = release
    args.sha = "c" * 40
    reasons = receipt.verify(args)
    assert any("revision" in r for r in reasons) and any("candidate" in r for r in reasons)
