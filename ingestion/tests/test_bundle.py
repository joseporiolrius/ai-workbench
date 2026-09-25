"""scripts/ingest_bundle.py: revision binding, size limit, secret refusal, identities."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "scripts/ingest_bundle.py"
TRACKED = ["docs/study-guides", "ingestion/corpus.py", "ingestion/ingest.py", "ingestion/rag.py",
           "ingestion/uv.lock", "rag-settings.yaml", "course-artifacts.yaml", ".gitignore", "k8s/ingest-job.yaml", SCRIPT]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "wb"
    for rel in TRACKED:
        src, dst = ROOT / rel, r / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    git(r, "init", "-q")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def run(repo, sha=None, out=None):
    env = {**os.environ, "RELEASE_SHA": sha or git(repo, "rev-parse", "HEAD"),
           "RELEASE_STATE_DIR": str(out or repo.parent / "state")}
    return subprocess.run([sys.executable, SCRIPT], cwd=repo, env=env, capture_output=True, text=True)


def identity(repo):
    return json.loads((repo.parent / "state" / "bundle-identity.json").read_text())


def test_clean_release_builds_revision_named_bundle(repo):
    sha = git(repo, "rev-parse", "HEAD")
    result = run(repo)
    assert result.returncode == 0, result.stderr
    ident = identity(repo)
    assert ident["revision"] == sha and ident["collection"] == f"study_guides_{sha}"
    assert ident["configmap"] == f"ingest-bundle-{sha}" and ident["configmap_bytes"] <= 512 * 1024
    assert ident["image"].startswith("ghcr.io/oriolrius/workbench-ingestion@sha256:")
    cm = json.loads((repo.parent / "state" / "bundle-configmap.json").read_text())
    keys = set(cm["data"])
    assert "docs__study-guides__session-06-terraform-iac.md" in keys and "ingestion__ingest.py" in keys
    assert {"rag-settings.yaml", "course-artifacts.yaml", "ingestion__uv.lock"} <= keys
    assert not any(k.startswith("ingestion__tests") for k in keys)
    assert cm["metadata"]["labels"]["course.dbai/revision"] == sha
    assert cm["metadata"]["annotations"]["course.dbai/corpus-hash"] == ident["corpus_hash"]
    assert git(repo, "status", "--porcelain") == ""  # nothing written into the checkout
    job = json.loads((repo.parent / "state" / "ingest-job.json").read_text())
    pod = job["spec"]["template"]["spec"]
    assert job["metadata"]["name"] == f"ingest-docs-{sha[:12]}" and job["spec"]["backoffLimit"] == 0
    assert pod["containers"][0]["image"] == ident["image"]
    assert pod["containers"][0]["args"][-3:] == [ident["collection"], "--revision", sha]
    env = {e["name"]: e for e in pod["containers"][0]["env"]}
    assert env["QDRANT_URL"]["value"] == "http://workbench-qdrant.workbench.svc:6333"
    assert env["COURSE_VIRTUAL_KEY"]["valueFrom"]["secretKeyRef"] == {"name": "workbench-keys", "key": "COURSE_VIRTUAL_KEY"}
    vol = pod["volumes"][0]["configMap"]
    assert vol["name"] == ident["configmap"] and {"key": "ingestion__ingest.py", "path": "ingestion/ingest.py"} in vol["items"]
    assert "${" not in json.dumps(job)


@pytest.mark.parametrize("sha, message", [("abc123", "full 40-hex"), ("0" * 40, "not the release SHA")])
def test_bad_or_mismatched_sha_is_refused(repo, sha, message):
    result = run(repo, sha=sha)
    assert result.returncode == 1 and message in result.stderr
    assert not (repo.parent / "state" / "bundle-configmap.json").exists()


def test_dirty_or_untracked_checkout_is_refused(repo):
    (repo / "docs/study-guides/extra.md").write_text("# untracked guide\n")
    result = run(repo)
    assert result.returncode == 1 and "uncommitted or untracked" in result.stderr


def test_oversized_bundle_fails_with_size_error(repo):
    (repo / "docs/study-guides/huge.md").write_text("# Huge\n\n" + "word " * 120_000)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "huge")
    result = run(repo)
    assert result.returncode == 1
    assert "512 KiB" in result.stderr and "docs/study-guides/huge.md" in result.stderr
    assert not (repo.parent / "state" / "bundle-configmap.json").exists()


@pytest.mark.parametrize("secret", ["sk-" + "A1b2C3d4" * 3, "-----BEGIN OPENSSH PRIVATE KEY-----", "AKIA" + "Z" * 16])
def test_credentials_are_never_bundled(repo, secret):
    (repo / "docs/study-guides/leak.md").write_text(f"# Leak\n\nkey = {secret}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "leak")
    result = run(repo)
    assert result.returncode == 1 and "looks like a credential" in result.stderr and "leak.md" in result.stderr


def test_new_faq_revision_changes_content_identity_not_image(repo):
    assert run(repo).returncode == 0
    first = identity(repo)
    (repo / "docs/study-guides/session-13-defense-faq.md").write_text(
        "# Session 13 — Defense FAQ\n\nEvery student submits a 4-minute recorded demo.\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "faq")
    assert run(repo).returncode == 0
    second = identity(repo)
    assert second["revision"] != first["revision"]
    assert second["corpus_hash"] != first["corpus_hash"] and second["bundle_hash"] != first["bundle_hash"]
    assert second["corpus_documents"] == first["corpus_documents"] + 1
    assert second["image"] == first["image"]
