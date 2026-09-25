"""S12 retrieval gate: the expected study guide must be in the top k for at least
`threshold` of the golden questions (default hit@3 >= 0.8). See evals/conftest.py."""

import pytest

import corpus


def test_golden_set_is_valid(golden_path):
    corpus.load_golden(golden_path, corpus.select_corpus("docs/study-guides"))


def test_question(question, evaluation):
    """Per-question result: PASSED on a hit; XFAIL (visible, not gate-breaking) on a miss."""
    result = next(r for r in evaluation["questions"] if r["id"] == question["id"])
    if not result["hit"]:
        pytest.xfail(f"miss: expected {result['expected_source']}, retrieved {result['retrieved']}")


def test_retrieval_gate(evaluation):
    hits, total, threshold = evaluation["hits"], evaluation["total"], evaluation["threshold"]
    assert total > 0, "no golden questions were evaluated"
    assert hits >= evaluation["required"], (
        f"retrieval gate FAILED: hit@{evaluation['k']} = {hits}/{total} = {hits / total:.2f} < threshold {threshold}")
