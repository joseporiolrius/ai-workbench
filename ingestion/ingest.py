"""Ingest the study-guide corpus into a candidate Qdrant collection.

    documents -> chunks -> course-gateway embeddings -> Qdrant upsert

Run from the ai-workbench repository root (paths are root-relative):

    uv run --project ingestion --locked python ingestion/ingest.py \
        --docs docs/study-guides --collection study_guides_manual

Needs COURSE_VIRTUAL_KEY in the environment and Qdrant at QDRANT_URL
(default http://127.0.0.1:6333). The ingestion alias comes from rag-settings.yaml.
The candidate is complete only when this prints COMPLETE and exits 0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import corpus
import rag


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest docs into a candidate collection.")
    parser.add_argument("--docs", required=True, help="corpus directory, e.g. docs/study-guides")
    parser.add_argument("--collection", required=True, help="candidate, e.g. study_guides_manual or study_guides_<SHA>")
    parser.add_argument("--settings", default="rag-settings.yaml")
    parser.add_argument("--revision", help="source revision to record (default: git HEAD, +dirty if modified)")
    args = parser.parse_args(argv)

    qdrant, created = None, False
    try:
        # 1. Read and validate every input before touching any service.
        settings = rag.load_settings(args.settings)
        contract = rag.contract()
        documents = corpus.select_corpus(args.docs)
        chunks = [c for d in documents for c in rag.chunk_document(d, settings["chunk_size"], settings["chunk_overlap"])]
        key = rag.course_key()
        model = settings["embedding_model"]
        provenance = {
            "corpus_hash": corpus.corpus_hash(documents),
            "corpus_revision": args.revision or rag.git_revision([args.docs, args.settings, "ingestion"]),
            "corpus_chunks": len(chunks),
            "embedding_model": model,
            "settings_hash": rag.sha256_files([Path(args.settings)]),
            "ingestion_source_hash": rag.sha256_files(sorted(Path("ingestion").glob("*.py"))),
        }
        print(f"corpus: {len(documents)} documents -> {len(chunks)} chunks "
              f"(chunk_size {settings['chunk_size']}, overlap {settings['chunk_overlap']})")
        print(f"corpus_hash: {provenance['corpus_hash']}  revision: {provenance['corpus_revision']}")

        # 2. Refuse protected targets (aliases, S10 fixture) and apply the retry policy.
        qdrant = rag.Qdrant()
        state = rag.check_writable(qdrant, args.collection, settings["collection_prefix"])
        if state == "live":
            # A live candidate is never reset or upserted: reuse it only if it is provably the same.
            diff = rag.provenance_diff(qdrant, args.collection, provenance)
            if diff:
                raise rag.RagError(
                    f"{args.collection!r} is LIVE and its stored provenance differs from these inputs — refusing "
                    "to touch it (points and alias unchanged). Explicit recovery: release a new commit/tag, or "
                    "restore the alias to a verified collection (docs/RAG_RELEASE.md §3):\n  " + "\n  ".join(diff))
            print(f"REUSED live candidate {args.collection!r}: stored provenance matches "
                  f"(revision {provenance['corpus_revision']}, corpus {provenance['corpus_hash'][:12]}); nothing written")
            return 0
        release_named = args.collection == f"{settings['collection_prefix']}_{provenance['corpus_revision']}"
        if state == "exists" and release_named:
            diff = rag.provenance_diff(qdrant, args.collection, provenance)
            stored_revision = qdrant.sample_payload(args.collection).get("corpus_revision")
            if diff and stored_revision == provenance["corpus_revision"]:
                raise rag.RagError(
                    f"{args.collection!r} was built for revision {stored_revision} from DIFFERENT inputs; changed "
                    "source/settings/corpus under an old identity are rejected. Commit and tag a new release:\n  "
                    + "\n  ".join(diff))

        # 3. Embed everything first: a gateway failure leaves Qdrant untouched.
        print(f"embedding with {model!r} via {contract['gateway']} ...")
        vectors = rag.embed([c.text for c in chunks], model, contract["gateway"], key)
        rag.spot_check([c.text for c in chunks], vectors, model, contract["gateway"], key)
        dimension = len(vectors[0])
        if any(len(v) != dimension for v in vectors) or dimension != contract["dimension"]:
            raise rag.RagError(f"{model!r} returned dimension {dimension}; the course contract requires "
                               f"{contract['dimension']} (a dimension error is not a valid candidate)")

        # 4. Recreate the candidate and upsert every chunk with its provenance.
        qdrant.recreate(args.collection, dimension)
        created = True
        points = [{
            "id": rag.point_id(c.source, c.index),
            "vector": v,
            "payload": {"text": c.text, "source": c.source, "title": c.title, "section": c.section,
                        "chunk_index": c.index, "citation": f"{c.source} § {c.section}",
                        "source_sha256": next(d.sha256 for d in documents if d.path == c.source), **provenance},
        } for c, v in zip(chunks, vectors)]
        qdrant.upsert(args.collection, points)

        # 5. Complete only if Qdrant holds exactly what we planned.
        stored = qdrant.count(args.collection)
        if stored != len(chunks):
            raise rag.RagError(f"stored {stored} points, expected {len(chunks)}")
    except corpus.CorpusError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        if created:
            try:
                qdrant.delete(args.collection)
                print(f"removed partial collection {args.collection!r}; it is NOT a candidate", file=sys.stderr)
            except corpus.CorpusError:
                print(f"WARNING: partial collection {args.collection!r} could not be removed; it is NOT a "
                      "complete candidate (search/eval refuse it). Re-run ingestion to recreate it.", file=sys.stderr)
        return 1
    print(f"COMPLETE candidate {args.collection!r}: {stored} points, dim {dimension}, model {model!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
