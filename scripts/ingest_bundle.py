"""Build the revision-named ingestion bundle (ConfigMap) for one release SHA (S12, RAG-01).

Run INSIDE the exact-SHA release worktree, normally through scripts/with-release.sh:

    scripts/with-release.sh <SHA> uv run --project ingestion --locked python scripts/ingest_bundle.py

It reads RELEASE_SHA (or --sha) and RELEASE_STATE_DIR (or --out-dir). It writes two files to the
state dir, outside tracked source, and changes nothing in Kubernetes or Qdrant:

- ``bundle-configmap.json``: ConfigMap ``ingest-bundle-<SHA>`` whose items mount at /workspace
  exactly like the checkout. It holds the selected study guides, the ingestion source and lock,
  rag-settings.yaml and course-artifacts.yaml.
- ``bundle-identity.json``: the revision, candidate collection ``study_guides_<SHA>``, corpus
  hash, bundle hash, sizes and the pinned ingestion image digest.

It refuses to build (exit 1) when the SHA is not the clean HEAD, when the serialized ConfigMap
exceeds 512 KiB, or when any bundled file looks like it contains a credential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the release checkout
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
import corpus  # noqa: E402
import yaml  # noqa: E402

DOCS = "docs/study-guides"
FIXED_FILES = ["rag-settings.yaml", "course-artifacts.yaml", "ingestion/uv.lock"]
LIMIT = 512 * 1024
NAMESPACE = "workbench"
SECRET_PATTERNS = {
    "course/OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
}


class BundleError(Exception):
    pass


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def check_checkout(sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha or ""):
        raise BundleError(f"release SHA must be a full 40-hex commit, got {sha!r}")
    head = git("rev-parse", "HEAD")
    if head != sha:
        raise BundleError(f"checkout HEAD is {head}, not the release SHA {sha} (run through scripts/with-release.sh)")
    dirty = git("status", "--porcelain")
    if dirty:
        raise BundleError("checkout has uncommitted or untracked changes; a bundle is built only from a clean "
                          "release checkout:\n" + dirty)


def bundle_files() -> list[str]:
    documents = corpus.select_corpus(DOCS)
    sources = sorted(p.as_posix() for p in Path("ingestion").glob("*.py"))
    missing = [f for f in FIXED_FILES + ["ingestion/ingest.py"] if not Path(f).is_file()]
    if missing:
        raise BundleError(f"required bundle inputs missing: {missing}")
    paths = sorted({d.path for d in documents} | set(sources) | set(FIXED_FILES), key=str.encode)
    ambiguous = [p for p in paths if "__" in p]
    if ambiguous:  # keys encode '/' as '__', so a literal '__' could not be mapped back
        raise BundleError(f"bundle paths may not contain '__': {ambiguous}")
    return paths


def ingestion_image() -> str:
    manifest = yaml.safe_load(Path("course-artifacts.yaml").read_text())
    for record in manifest.get("artifacts", []):
        if record.get("id") == "image-workbench-ingestion" and record.get("status") == "qualified":
            identity = record["identity"]
            return f"{identity['image_ref'].split(':')[0]}@{identity['digest']}"
    raise BundleError("course-artifacts.yaml has no qualified image-workbench-ingestion record")


def scan_secrets(files: dict[str, str]) -> None:
    hits = [f"{path}: {label}" for path, text in files.items()
            for label, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    if hits:
        raise BundleError("refusing to bundle content that looks like a credential:\n  " + "\n  ".join(hits))


def build(sha: str) -> tuple[dict, dict]:
    paths = bundle_files()
    files = {p: Path(p).read_text(encoding="utf-8") for p in paths}
    scan_secrets(files)
    documents = corpus.select_corpus(DOCS)
    manifest = "".join(f"{hashlib.sha256(files[p].encode()).hexdigest()}  {p}\n" for p in paths)
    identity = {
        "revision": sha,
        "collection": f"study_guides_{sha}",
        "configmap": f"ingest-bundle-{sha}",
        "namespace": NAMESPACE,
        "corpus_hash": corpus.corpus_hash(documents),
        "corpus_documents": len(documents),
        "bundle_hash": hashlib.sha256(manifest.encode()).hexdigest(),
        "bundle_files": len(paths),
        "image": ingestion_image(),
    }
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": identity["configmap"],
            "namespace": NAMESPACE,
            "labels": {"app.kubernetes.io/part-of": "workbench-rag", "course.dbai/revision": sha},
            "annotations": {f"course.dbai/{k.replace('_', '-')}": str(v) for k, v in identity.items()
                            if k in ("revision", "corpus_hash", "bundle_hash", "collection", "image")},
        },
        # ConfigMap keys cannot contain '/': the Job maps each key back to its path under /workspace.
        "data": {p.replace("/", "__"): files[p] for p in paths},
    }
    size = len(json.dumps(configmap, separators=(",", ":")).encode())
    identity["configmap_bytes"] = size
    if size > LIMIT:
        biggest = sorted(paths, key=lambda p: -len(files[p].encode()))[:3]
        raise BundleError(f"serialized bundle is {size} bytes, over the {LIMIT}-byte (512 KiB) ConfigMap limit; "
                          f"largest inputs: " + ", ".join(f"{p} ({len(files[p].encode())} B)" for p in biggest))
    return configmap, identity


def items(configmap: dict) -> list[dict]:
    """volume items that recreate the checkout layout under /workspace."""
    return [{"key": key, "path": key.replace("__", "/")} for key in sorted(configmap["data"])]


def render_job(configmap: dict, identity: dict, deadline: int = 600) -> dict:
    """k8s/ingest-job.yaml with this revision's values and bundle items filled in."""
    values = {
        "JOB_NAME": f"ingest-docs-{identity['revision'][:12]}",
        "REVISION": identity["revision"], "COLLECTION": identity["collection"],
        "CORPUS_HASH": identity["corpus_hash"], "BUNDLE_HASH": identity["bundle_hash"],
        "CONFIGMAP": identity["configmap"], "IMAGE": identity["image"], "DEADLINE_SECONDS": str(deadline),
    }
    try:
        job = yaml.safe_load(string.Template(Path("k8s/ingest-job.yaml").read_text()).substitute(values))
    except (KeyError, ValueError) as exc:
        raise BundleError(f"k8s/ingest-job.yaml has an unknown placeholder: {exc}") from exc
    job["spec"]["template"]["spec"]["volumes"][0]["configMap"]["items"] = items(configmap)
    for name in ("RAG_QUALIFICATION_BUDGET", "RAG_QUALIFICATION_INTERVAL_SECONDS"):
        if name in os.environ:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": name, "value": os.environ[name]})
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the revision-named ingestion bundle.")
    parser.add_argument("--sha", default=os.environ.get("RELEASE_SHA"), help="full release SHA (default: $RELEASE_SHA)")
    parser.add_argument("--out-dir", default=os.environ.get("RELEASE_STATE_DIR"),
                        help="where to write the bundle (default: $RELEASE_STATE_DIR, outside tracked source)")
    parser.add_argument("--deadline", type=int, default=int(os.environ.get("INGEST_DEADLINE_SECONDS", 600)),
                        help="Job activeDeadlineSeconds written into ingest-job.json")
    args = parser.parse_args(argv)
    try:
        if not args.out_dir:
            raise BundleError("no output dir: set RELEASE_STATE_DIR (scripts/with-release.sh does) or --out-dir")
        check_checkout(args.sha or "")
        configmap, identity = build(args.sha)
        job = render_job(configmap, identity, args.deadline)
        identity["job"] = job["metadata"]["name"]
    except (BundleError, corpus.CorpusError, subprocess.CalledProcessError, OSError, UnicodeDecodeError) as exc:
        print(f"ingest-bundle: ERROR: {exc}", file=sys.stderr)
        return 1
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bundle-configmap.json").write_text(json.dumps(configmap, indent=1) + "\n")
    (out / "bundle-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (out / "ingest-job.json").write_text(json.dumps(job, indent=1) + "\n")
    print(json.dumps(identity, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
