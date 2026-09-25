"""Evaluation receipts: the only evidence that lets a candidate be promoted (S12, RAG-05).

    receipt.py make   --state DIR (--sha SHA | --manual CANDIDATE)          # run-eval.sh calls this
    receipt.py verify --state DIR (--sha SHA | --manual CANDIDATE) [--qdrant-url URL]

``make`` turns ``eval-results.json`` (written by the evaluator) into ``receipt.json`` in the state
dir, for passing AND failing evaluations. ``verify`` accepts a receipt only if it passed, if its
result is internally consistent, and if every identity in it still matches what would be promoted:
the requested revision and candidate, the corpus/settings/source recomputed from THIS checkout,
the ingestion and query model aliases, the pinned ingestion image, the evaluated results file and,
when Qdrant is reachable, the stored candidate itself. Any difference is rejected with a reason;
fresh evidence means re-running scripts/run-eval.sh. Exit: 0 accepted/written, 1 rejected/error.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
import corpus  # noqa: E402
import rag  # noqa: E402

SCHEMA = "dbai/rag-receipt/v1"
GATE_K, GATE_THRESHOLD = 3, 0.8
MANUAL_IMAGE = "local uv environment (manual mode, no ingestion image)"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkout_identity(settings_path: str = "rag-settings.yaml") -> dict:
    """What THIS checkout would ingest, recomputed now (never trusted from a file)."""
    settings = rag.load_settings(settings_path)
    documents = corpus.select_corpus("docs/study-guides")
    return {
        "corpus_hash": corpus.corpus_hash(documents),
        "settings_hash": rag.sha256_files([Path(settings_path)]),
        "ingestion_source_hash": rag.sha256_files(sorted(Path("ingestion").glob("*.py"))),
        "ingestion_model": settings["embedding_model"],
        "query_model": rag.contract()["query_model"],
    }


def pinned_image() -> str:
    import yaml
    for record in yaml.safe_load(Path("course-artifacts.yaml").read_text()).get("artifacts", []):
        if record.get("id") == "image-workbench-ingestion" and record.get("status") == "qualified":
            return f"{record['identity']['image_ref'].split(':')[0]}@{record['identity']['digest']}"
    raise rag.RagError("course-artifacts.yaml has no qualified image-workbench-ingestion record")


def expected(args) -> tuple[str, str, str]:
    """(mode, revision, candidate) the caller asks for."""
    if args.sha:
        return "release", args.sha, f"study_guides_{args.sha}"
    return "manual", rag.git_revision(["docs/study-guides", "rag-settings.yaml", "ingestion"]), args.manual


def make(args) -> dict:
    state = Path(args.state)
    results_path = state / "eval-results.json"
    results = json.loads(results_path.read_text())
    mode, revision, candidate = expected(args)
    c = results["candidate"]
    receipt = {
        "schema": SCHEMA, "mode": mode, "revision": revision, "candidate": candidate,
        "evaluated_collection": c["collection"], "physical_collection": c["physical"], "points": c["points"],
        "stored_revision": c["corpus_revision"], "corpus_hash": c["corpus_hash"], "settings_hash": c["settings_hash"],
        "ingestion_source_hash": c["ingestion_source_hash"], "ingestion_model": c["embedding_model"],
        "query_model": results["query_model"],
        "image": json.loads((state / "bundle-identity.json").read_text())["image"] if mode == "release" else MANUAL_IMAGE,
        "k": results["k"], "threshold": results["threshold"], "required": results["required"],
        "hits": results["hits"], "total": results["total"], "score": results["score"], "passed": results["passed"],
        "eval_results_sha256": sha256_file(results_path),
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (state / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def verify(args) -> list[str]:
    """Reasons to reject ([] = accepted)."""
    state = Path(args.state)
    path = state / "receipt.json"
    if not path.is_file():
        return [f"no receipt at {path}: evaluate the candidate first (scripts/run-eval.sh)"]
    try:
        r = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"receipt is not valid JSON: {exc}"]
    required_keys = {"schema", "mode", "revision", "candidate", "points", "corpus_hash", "settings_hash",
                     "ingestion_source_hash", "ingestion_model", "query_model", "image", "k", "threshold",
                     "required", "hits", "total", "passed", "eval_results_sha256", "stored_revision"}
    if r.get("schema") != SCHEMA or required_keys - set(r):
        return [f"receipt schema invalid (schema {r.get('schema')!r}, missing {sorted(required_keys - set(r))})"]
    reasons = []
    mode, revision, candidate = expected(args)
    # 1. the result: passed, consistent, never weaker than the course gate
    if not r["passed"]:
        reasons.append(f"evaluation FAILED: hit@{r['k']} {r['hits']}/{r['total']} < threshold {r['threshold']}")
    need = math.ceil(round(r["threshold"] * r["total"], 9)) if r["total"] else None
    if r["total"] <= 0 or r["required"] != need or (r["hits"] >= r["required"]) != r["passed"]:
        reasons.append("result fields are inconsistent (hits/total/required/passed do not agree)")
    if r["k"] > GATE_K or r["threshold"] < GATE_THRESHOLD:
        reasons.append(f"gate weaker than hit@{GATE_K} >= {GATE_THRESHOLD} (k={r['k']}, threshold={r['threshold']})")
    # 2. the request: same mode, revision and candidate
    for field, want in (("mode", mode), ("revision", revision), ("candidate", candidate)):
        if r[field] != want:
            reasons.append(f"{field}: receipt {r[field]!r} != requested {want!r}")
    if r["stored_revision"] != revision:
        reasons.append(f"the evaluated candidate was built from {r['stored_revision']!r}, not {revision!r}")
    # 3. the inputs: recomputed from this checkout
    now = checkout_identity()
    for field, value in now.items():
        if r[field] != value:
            reasons.append(f"{field}: receipt {r[field]!r} != this checkout {value!r} (stale evidence)")
    image = pinned_image() if mode == "release" else MANUAL_IMAGE
    if r["image"] != image:
        reasons.append(f"image: receipt {r['image']!r} != pinned {image!r}")
    # 4. the evidence file it was made from
    results = state / "eval-results.json"
    if not results.is_file() or sha256_file(results) != r["eval_results_sha256"]:
        reasons.append("eval-results.json is missing or changed since the receipt was made")
    # 5. the candidate itself, when Qdrant is reachable
    if args.qdrant_url:
        qdrant = rag.Qdrant(args.qdrant_url)
        try:
            stored = qdrant.sample_payload(candidate) if qdrant.exists(candidate) else {}
            count = qdrant.count(candidate) if stored else 0
        except rag.RagError as exc:
            return reasons + [f"cannot read candidate {candidate!r} from Qdrant: {exc}"]
        if not stored:
            reasons.append(f"candidate {candidate!r} does not exist in Qdrant")
        else:
            for field, key in (("corpus_hash", "corpus_hash"), ("stored_revision", "corpus_revision"),
                               ("ingestion_model", "embedding_model"), ("settings_hash", "settings_hash"),
                               ("ingestion_source_hash", "ingestion_source_hash")):
                if stored.get(key) != r[field]:
                    reasons.append(f"stored candidate {key} {stored.get(key)!r} != receipt {r[field]!r}")
            if count != r["points"]:
                reasons.append(f"stored candidate has {count} points, receipt says {r['points']}")
    return reasons


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=["make", "verify"])
    parser.add_argument("--state", required=True, help="release state dir holding eval-results.json / receipt.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sha", help="release mode: full SHA")
    group.add_argument("--manual", help="manual mode: candidate collection, e.g. study_guides_manual")
    parser.add_argument("--qdrant-url", help="also check the stored candidate (verify)")
    args = parser.parse_args(argv)
    try:
        if args.action == "make":
            r = make(args)
            print(f"receipt: {r['candidate']} hit@{r['k']} {r['hits']}/{r['total']} "
                  f"{'PASS' if r['passed'] else 'FAIL'} -> {Path(args.state) / 'receipt.json'}")
            return 0
        reasons = verify(args)
    except (OSError, KeyError, json.JSONDecodeError, corpus.CorpusError) as exc:
        print(f"receipt: ERROR: {exc}", file=sys.stderr)
        return 1
    if reasons:
        print("receipt REJECTED:\n  " + "\n  ".join(reasons), file=sys.stderr)
        return 1
    print("receipt ACCEPTED: passing evaluation matches this revision, candidate, inputs and image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
