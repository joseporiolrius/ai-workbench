"""Corpus/golden-set validation: the real corpus passes, malformed inputs fail."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOCS = "docs/study-guides"
GOLDEN = ROOT / "evals/golden_set.yaml"


@pytest.fixture
def repo(tmp_path):
    """A tiny repo: two documents and a valid ten-question golden set."""
    docs = tmp_path / DOCS
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# A\nalpha\n")
    (docs / "b.md").write_text("# B\nbeta\n")
    questions = [{"id": f"q{n:02d}", "question": f"question {n}?",
                  "expected_source": f"{DOCS}/{'a' if n % 2 else 'b'}.md"} for n in range(1, 11)]
    golden = {"version": 1, "threshold": 0.8, "k": 3, "questions": questions}
    return tmp_path, golden


def check(tmp_path, golden):
    path = tmp_path / "golden.yaml"
    path.write_text(yaml.safe_dump(golden, sort_keys=False))
    return corpus.load_golden(path, corpus.select_corpus(DOCS, root=tmp_path))


def test_real_corpus_and_golden_set_are_valid():
    documents = corpus.select_corpus(DOCS, root=ROOT)
    golden = corpus.load_golden(GOLDEN, documents)
    assert len(golden["questions"]) == 10
    assert golden["threshold"] == 0.8 and golden["k"] == 3
    assert {q["expected_source"] for q in golden["questions"]} <= {d.path for d in documents}


def test_initial_corpus_reserves_the_defense_faq():
    names = {Path(d.path).name for d in corpus.select_corpus(DOCS, root=ROOT)}
    assert corpus.RESERVED_FAQ not in names


def test_corpus_hash_matches_sha256sum_manifest(tmp_path, repo):
    root, _ = repo
    documents = corpus.select_corpus(DOCS, root=root)
    shell = subprocess.run(f"sha256sum {DOCS}/*.md | LC_ALL=C sort -k2 | sha256sum",
                           shell=True, cwd=root, capture_output=True, text=True, check=True)
    assert shell.stdout.split()[0] == corpus.corpus_hash(documents)


def test_corpus_hash_changes_with_content_and_path(repo):
    root, _ = repo
    before = corpus.corpus_hash(corpus.select_corpus(DOCS, root=root))
    (root / DOCS / "b.md").write_text("# B\nbeta changed\n")
    changed = corpus.corpus_hash(corpus.select_corpus(DOCS, root=root))
    (root / DOCS / "b.md").rename(root / DOCS / "c.md")
    renamed = corpus.corpus_hash(corpus.select_corpus(DOCS, root=root))
    assert len({before, changed, renamed}) == 3


def test_valid_fixture_passes(repo):
    assert len(check(*repo)["questions"]) == 10


@pytest.mark.parametrize("mutate, message", [
    (lambda g: g["questions"][0].update(expected_source=f"{DOCS}/missing.md"), "is not a corpus document"),
    (lambda g: g["questions"][1].update(id="q01"), "duplicate id"),
    (lambda g: g["questions"][2].update(id=""), "'id' must be a non-empty string"),
    (lambda g: g["questions"][2].update(id="   "), "'id' must be a non-empty string"),
    (lambda g: g["questions"][3].pop("id"), "missing keys ['id']"),
    (lambda g: g["questions"][3].update(question=""), "'question' must be a non-empty string"),
    (lambda g: g["questions"][4].update(question="Question 1?"), "duplicate question"),
    (lambda g: g["questions"][5].update(answer="x"), "unknown keys ['answer']"),
    (lambda g: g["questions"].__setitem__(6, "just a string"), "must be a mapping"),
    (lambda g: g["questions"][7].update(expected_source=3), "'expected_source' must be a non-empty string"),
    (lambda g: g["questions"].pop(), "need at least 10 questions"),
    (lambda g: g.update(threshold=1.5), "threshold must be a number"),
    (lambda g: g.update(k=0), "k must be a positive integer"),
    (lambda g: g.update(extra=True), "unknown top-level keys"),
])
def test_malformed_golden_set_fails(repo, mutate, message):
    root, golden = repo
    mutate(golden)
    with pytest.raises(corpus.CorpusError) as err:
        check(root, golden)
    assert message in str(err.value)


def test_non_mapping_and_bad_yaml_fail(repo):
    root, _ = repo
    documents = corpus.select_corpus(DOCS, root=root)
    for content in ["- just\n- a list\n", "questions: [unclosed\n"]:
        (root / "g.yaml").write_text(content)
        with pytest.raises(corpus.CorpusError):
            corpus.load_golden(root / "g.yaml", documents)


def test_empty_or_missing_corpus_fails(tmp_path):
    with pytest.raises(corpus.CorpusError, match="not found"):
        corpus.select_corpus(DOCS, root=tmp_path)
    (tmp_path / DOCS).mkdir(parents=True)
    with pytest.raises(corpus.CorpusError, match="no \\*.md documents"):
        corpus.select_corpus(DOCS, root=tmp_path)
    (tmp_path / DOCS / "empty.md").write_text("  \n")
    with pytest.raises(corpus.CorpusError, match="empty document"):
        corpus.select_corpus(DOCS, root=tmp_path)


def test_cli_exit_codes(repo):
    root, golden = repo
    (root / "golden.yaml").write_text(yaml.safe_dump(golden))
    cli = [sys.executable, str(Path(corpus.__file__)), "--docs", DOCS, "--golden", "golden.yaml"]
    ok = subprocess.run(cli, cwd=root, capture_output=True, text=True)
    assert ok.returncode == 0 and "golden set: 10 questions valid" in ok.stdout
    golden["questions"][0]["expected_source"] = f"{DOCS}/nope.md"
    (root / "golden.yaml").write_text(yaml.safe_dump(golden))
    bad = subprocess.run(cli, cwd=root, capture_output=True, text=True)
    assert bad.returncode == 1 and "nope.md" in bad.stderr


def test_configmap_style_symlinks_do_not_leak_into_paths_or_hash(repo, tmp_path_factory):
    """kubelet mounts ConfigMap items as docs -> ..data/docs -> ..<timestamp>/docs."""
    root, _ = repo
    expected = corpus.select_corpus(DOCS, root=root)
    mount = tmp_path_factory.mktemp("workspace")
    real = mount / "..2026_09_24_20_15_25.123" / "docs"
    real.parent.mkdir()
    (root / "docs").rename(real)
    (mount / "..data").symlink_to("..2026_09_24_20_15_25.123")
    (mount / "docs").symlink_to("..data/docs")
    mounted = corpus.select_corpus(DOCS, root=mount)
    assert [d.path for d in mounted] == [d.path for d in expected] == [f"{DOCS}/a.md", f"{DOCS}/b.md"]
    assert corpus.corpus_hash(mounted) == corpus.corpus_hash(expected)
