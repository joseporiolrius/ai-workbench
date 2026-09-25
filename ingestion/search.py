"""Smoke-search a study-guide collection and print cited results.

Run from the ai-workbench repository root:

    uv run --project ingestion --locked python ingestion/search.py \
        "What is infrastructure as code?" --collection study_guides_manual

The question is ALWAYS embedded with the course query alias (course-embed, from
course-artifacts.yaml › retrieval), whatever alias built the collection. Reading
the live alias (--collection study_guides) is allowed; search never writes.
"""

from __future__ import annotations

import argparse
import sys

import corpus
import rag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search a study-guide collection.")
    parser.add_argument("question")
    parser.add_argument("--collection", required=True, help="candidate or alias, e.g. study_guides_manual")
    parser.add_argument("--top-k", type=int, help="results to return (default: rag-settings.yaml top_k)")
    parser.add_argument("--settings", default="rag-settings.yaml")
    args = parser.parse_args(argv)
    try:
        top_k = args.top_k or rag.load_settings(args.settings)["top_k"]
        contract = rag.contract()
        key = rag.course_key()
        qdrant = rag.Qdrant()
        info = rag.verify_complete(qdrant, args.collection)
        hits = rag.retrieve(qdrant, args.collection, args.question, top_k, contract, key)
    except corpus.CorpusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    target = info["collection"] + (f" -> {info['physical']}" if info["physical"] != info["collection"] else "")
    print(f"collection {target}: {info['points']} points, corpus_hash {info['corpus_hash'][:12]}, "
          f"revision {info['corpus_revision']}, ingested with {info['embedding_model']!r}")
    print(f"query model {contract['query_model']!r}, top_k {top_k}\n")
    for rank, hit in enumerate(hits, 1):
        snippet = " ".join(hit["text"].split("\n\n", 1)[-1].split())[:220]
        print(f"{rank}. [{hit['score']:.3f}] {hit['citation']}\n   {snippet}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
