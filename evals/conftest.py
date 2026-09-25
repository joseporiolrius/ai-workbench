"""Retrieval evaluation fixtures. Run from the repository root:

    QDRANT_COLLECTION=study_guides_manual \
        uv run --project ingestion --locked pytest evals/ -v

Environment: QDRANT_COLLECTION (required: the candidate to score), COURSE_VIRTUAL_KEY
(required), QDRANT_URL (default http://127.0.0.1:6333), GOLDEN_SET (default
evals/golden_set.yaml), EVAL_RESULTS (optional path for the nonsecret JSON results).
"""

import json
import math
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
import corpus  # noqa: E402
import rag  # noqa: E402

COURSE_QUERY_MODEL = "course-embed"  # fixed by the course contract, never by rag-settings.yaml
GATE_K, GATE_THRESHOLD = 3, 0.8      # a golden set may be stricter, never weaker


def required(threshold: float, total: int) -> int:
    """Minimum hits for a fraction threshold (0.8 of 10 -> 8, of 15 -> 12); exact, no float drift."""
    return math.ceil(round(threshold * total, 9))


def _golden_path() -> str:
    return os.environ.get("GOLDEN_SET", "evals/golden_set.yaml")


def pytest_generate_tests(metafunc):
    """One test per golden question, so `-v` shows every result."""
    if "question" in metafunc.fixturenames:
        try:
            documents = corpus.select_corpus("docs/study-guides")
            questions = corpus.load_golden(_golden_path(), documents)["questions"]
        except corpus.CorpusError:
            questions = []  # test_golden_set_is_valid reports why
        metafunc.parametrize("question", questions, ids=[q["id"] for q in questions])


@pytest.fixture(scope="session")
def golden_path() -> str:
    return _golden_path()


@pytest.fixture(scope="session")
def evaluation(pytestconfig):
    """Score the candidate once; every test reads this result."""
    collection = os.environ.get("QDRANT_COLLECTION", "").strip()
    if not collection:
        pytest.fail("QDRANT_COLLECTION is not set: name the candidate to evaluate, e.g. study_guides_manual")
    try:
        golden = corpus.load_golden(_golden_path(), corpus.select_corpus("docs/study-guides"))
        contract = rag.contract()
        if contract["query_model"] != COURSE_QUERY_MODEL:
            pytest.fail(f"contract query alias is {contract['query_model']!r}; the evaluator requires {COURSE_QUERY_MODEL!r}")
        if golden["k"] > GATE_K or golden["threshold"] < GATE_THRESHOLD:
            pytest.fail(f"golden set weakens the course gate (k={golden['k']}, threshold={golden['threshold']}); "
                        f"minimum is hit@{GATE_K} >= {GATE_THRESHOLD}")
        key = rag.course_key()
        qdrant = rag.Qdrant()
        candidate = rag.verify_complete(qdrant, collection)
        results = []
        for entry in golden["questions"]:
            hits = rag.retrieve(qdrant, collection, entry["question"], golden["k"], contract, key)
            sources = [h["source"] for h in hits]
            rank = sources.index(entry["expected_source"]) + 1 if entry["expected_source"] in sources else None
            results.append({"id": entry["id"], "expected_source": entry["expected_source"], "hit": rank is not None,
                            "rank": rank, "retrieved": sources, "scores": [round(h["score"], 4) for h in hits]})
    except corpus.CorpusError as exc:
        pytest.fail(f"evaluation could not run: {exc}")
    hits = sum(r["hit"] for r in results)
    summary = {
        "candidate": candidate, "query_model": contract["query_model"], "gateway": contract["gateway"],
        "golden_set": _golden_path(), "k": golden["k"], "threshold": golden["threshold"],
        "hits": hits, "total": len(results), "score": round(hits / len(results), 4),
        "required": required(golden["threshold"], len(results)),
        "passed": len(results) > 0 and hits >= required(golden["threshold"], len(results)), "questions": results,
    }
    if os.environ.get("EVAL_RESULTS"):
        Path(os.environ["EVAL_RESULTS"]).write_text(json.dumps(summary, indent=2) + "\n")
    pytestconfig._retrieval_summary = summary
    return summary


def pytest_terminal_summary(terminalreporter):
    summary = getattr(terminalreporter.config, "_retrieval_summary", None)
    if summary:
        c = summary["candidate"]
        terminalreporter.section("retrieval evaluation")
        terminalreporter.write_line(f"candidate {c['collection']} -> {c['physical']} ({c['points']} points), "
                                    f"corpus {c['corpus_hash'][:12]} @ {c['corpus_revision']}, "
                                    f"ingested with {c['embedding_model']!r}, queried with {summary['query_model']!r}")
        for r in summary["questions"]:
            where = f"rank {r['rank']}" if r["hit"] else "MISS -> " + ", ".join(Path(s).name for s in r["retrieved"])
            terminalreporter.write_line(f"  {r['id']:<6} {'HIT ' if r['hit'] else 'MISS'} {Path(r['expected_source']).name}  ({where})")
        verdict = "PASS" if summary["passed"] else "FAIL"
        terminalreporter.write_line(f"hit@{summary['k']} = {summary['hits']}/{summary['total']} = {summary['score']:.2f} "
                                    f"(threshold {summary['threshold']}: need {summary['required']}) -> {verdict}")
