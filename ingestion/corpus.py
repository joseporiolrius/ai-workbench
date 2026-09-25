"""Study-guide corpus identity and golden-set validation.

Run from the ai-workbench repository root:

    uv run --project ingestion --locked python ingestion/corpus.py \
        --docs docs/study-guides --golden evals/golden_set.yaml

The corpus is every ``*.md`` file directly inside the docs directory (not
recursive). Each file is cited by its repository-root-relative path, e.g.
``docs/study-guides/session-06-terraform-iac.md``.

The corpus hash is the SHA-256 of a ``sha256sum``-style manifest (one
``<sha256>  <path>`` line per file, sorted by path), so it can be reproduced
without Python:

    sha256sum docs/study-guides/*.md | LC_ALL=C sort -k2 | sha256sum

Exit status: 0 valid, 1 invalid corpus or golden set.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

RESERVED_FAQ = "session-13-defense-faq.md"
GOLDEN_KEYS = {"id", "question", "expected_source"}
TOP_LEVEL_KEYS = {"version", "threshold", "k", "questions"}
MIN_QUESTIONS = 10


class CorpusError(Exception):
    """The corpus or golden set is not usable; message says why."""


@dataclass(frozen=True)
class Document:
    path: str  # repository-root-relative citation path
    text: str
    sha256: str


def select_corpus(docs: str | Path, root: str | Path = ".") -> list[Document]:
    """Return the selected corpus documents, sorted by citation path."""
    # Lexical paths, never .resolve(): a Kubernetes ConfigMap mount is a tree of symlinks
    # (docs -> ..data/docs -> ..<timestamp>/docs) and resolving them would leak the
    # timestamped directory into every citation and into the corpus hash.
    root = Path(os.path.normpath(Path(root).absolute()))
    docs_dir = Path(os.path.normpath(root / docs))
    if not docs_dir.is_dir():
        raise CorpusError(f"docs directory not found: {docs}")
    if root != docs_dir and root not in docs_dir.parents:
        raise CorpusError(f"{docs} is outside the repository root {root}; run from the ai-workbench root")
    documents = []
    for file in sorted(docs_dir.glob("*.md")):
        rel = file.relative_to(root).as_posix()
        data = file.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorpusError(f"{rel}: not UTF-8 ({exc})") from exc
        if not text.strip():
            raise CorpusError(f"{rel}: empty document")
        documents.append(Document(rel, text, hashlib.sha256(data).hexdigest()))
    if not documents:
        raise CorpusError(f"no *.md documents in {docs}")
    documents.sort(key=lambda d: d.path.encode())
    return documents


def corpus_hash(documents: list[Document]) -> str:
    manifest = "".join(f"{d.sha256}  {d.path}\n" for d in documents)
    return hashlib.sha256(manifest.encode()).hexdigest()


def load_golden(golden: str | Path, documents: list[Document]) -> dict:
    """Parse and validate the golden set; raise CorpusError listing every problem."""
    try:
        data = yaml.safe_load(Path(golden).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CorpusError(f"golden set not found: {golden}") from exc
    except yaml.YAMLError as exc:
        raise CorpusError(f"golden set is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CorpusError("golden set must be a mapping with a 'questions' list")

    errors = []
    unknown = set(data) - TOP_LEVEL_KEYS
    if unknown:
        errors.append(f"unknown top-level keys: {sorted(unknown)}")
    threshold = data.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        errors.append(f"threshold must be a number in (0, 1], got {threshold!r}")
    k = data.get("k")
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        errors.append(f"k must be a positive integer, got {k!r}")
    questions = data.get("questions")
    if not isinstance(questions, list):
        raise CorpusError("; ".join(errors + ["'questions' must be a list"]))
    if len(questions) < MIN_QUESTIONS:
        errors.append(f"need at least {MIN_QUESTIONS} questions, found {len(questions)}")

    corpus_paths = {d.path for d in documents}
    seen_ids, seen_questions = set(), set()
    for n, entry in enumerate(questions, 1):
        where = f"questions[{n}]"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be a mapping with {sorted(GOLDEN_KEYS)}")
            continue
        missing, extra = GOLDEN_KEYS - set(entry), set(entry) - GOLDEN_KEYS
        if missing:
            errors.append(f"{where}: missing keys {sorted(missing)}")
        if extra:
            errors.append(f"{where}: unknown keys {sorted(extra)}")
        for key in GOLDEN_KEYS & set(entry):
            if not isinstance(entry[key], str) or not entry[key].strip():
                errors.append(f"{where}: '{key}' must be a non-empty string")
        qid = entry.get("id")
        if isinstance(qid, str) and qid.strip():
            where = f"{where} (id {qid})"
            if qid in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(qid)
        question = entry.get("question")
        if isinstance(question, str) and question.strip():
            normalized = " ".join(question.lower().split())
            if normalized in seen_questions:
                errors.append(f"{where}: duplicate question")
            seen_questions.add(normalized)
        source = entry.get("expected_source")
        if isinstance(source, str) and source.strip() and source not in corpus_paths:
            errors.append(f"{where}: expected_source {source!r} is not a corpus document")
    if errors:
        raise CorpusError("\n  ".join(["invalid golden set:"] + errors))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--docs", required=True, help="corpus directory, e.g. docs/study-guides")
    parser.add_argument("--golden", help="golden set to validate, e.g. evals/golden_set.yaml")
    args = parser.parse_args(argv)
    try:
        documents = select_corpus(args.docs)
        print(f"corpus: {len(documents)} documents, {sum(len(d.text.encode()) for d in documents)} bytes")
        for d in documents:
            print(f"  {d.sha256[:12]}  {d.path}")
        print(f"corpus_hash: {corpus_hash(documents)}")
        reserved = any(d.path.endswith("/" + RESERVED_FAQ) for d in documents)
        print(f"reserved {RESERVED_FAQ}: {'present' if reserved else 'absent (initial corpus)'}")
        if args.golden:
            golden = load_golden(args.golden, documents)
            print(f"golden set: {len(golden['questions'])} questions valid "
                  f"(hit@{golden['k']} threshold {golden['threshold']})")
    except CorpusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
