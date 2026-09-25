# Retrieval fixture qualification (instructor, before teaching S12)

The S12 gate and the decoy drill only teach something if the **frozen fixture** behaves as
intended on the real stack. The frozen fixture is `docs/study-guides/` (corpus hash) plus
`evals/golden_set.yaml`. There are two requirements:

- **good:** ingestion `course-embed`, queries `course-embed`. hit@3 ≥ 0.8.
- **decoy:** ingestion `course-embed-decoy`, queries `course-embed`. hit@3 < 0.8, with the
  **same** dimension and no transport error. A dimension error is a different fault and does
  not qualify.

The result is recorded in `course-artifacts.yaml › retrieval.qualification`.

## Procedure (live course VM, from the repo root)

```bash
export COURSE_VIRTUAL_KEY="$(kubectl -n workbench get secret workbench-keys -o jsonpath='{.data.COURSE_VIRTUAL_KEY}' | base64 -d)"
kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333 &
SHA=$(git rev-parse HEAD)
sed 's/^embedding_model: course-embed$/embedding_model: course-embed-decoy/' rag-settings.yaml > /tmp/rag-settings.decoy.yaml
uv run --project ingestion --locked python ingestion/ingest.py --docs docs/study-guides --collection study_guides_$SHA
uv run --project ingestion --locked python ingestion/ingest.py --docs docs/study-guides --collection study_guides_decoy_$SHA \
    --settings /tmp/rag-settings.decoy.yaml --revision $SHA+decoy-settings
QDRANT_COLLECTION=study_guides_$SHA       EVAL_RESULTS=/tmp/eval-good.json  uv run --project ingestion --locked pytest evals/ -v   # expect exit 0
QDRANT_COLLECTION=study_guides_decoy_$SHA EVAL_RESULTS=/tmp/eval-decoy.json uv run --project ingestion --locked pytest evals/ -v   # expect exit 1
```

Also check the extension in the browser UI, through Traefik and with `search_docs` enabled
(`docs/SEARCH_DOCS.md`). A course question must produce a `search_docs` card and a cited
answer. A general question must be answered with no tool card.

## Last qualification (2026-09-24)

| | ingestion alias | query alias | dim | hit@3 | gate |
|---|---|---|---|---|---|
| good | course-embed | course-embed | 4096 | 10/10 | PASS |
| decoy | course-embed-decoy | course-embed | 4096 | 2/10 | FAIL (as intended) |

The fixture was `ai-workbench@fcf13de`, corpus `8626868a…`, 163 chunks. It ran on the
ec2-console operations VM (k3s v1.30.5) with chart 0.3.0 and ingestion image
`workbench-ingestion:0.1.0@sha256:9ffe55ae…`. The same candidate, built by that image inside the
cluster, also scored 10/10. The decoy's 2/10 is **not a promise**: other corpora or questions
score differently, and the only contract is "below 0.8 with equal dimension".

**Re-verified 2026-09-25 with single-text embedding** (after the gateway batch-misorder fix,
`ai-workbench@cbd670c`/`66efa27`): good 10/10 and decoy 2/10 on the course VM, and 0/165 misaligned
live vectors. The original qualification used batched requests over fully cached, correctly ordered
batches. It is superseded by this run.

## When to requalify

Re-run the whole procedure and update `retrieval.qualification` after any change to:

- the corpus or the golden set;
- the chunk settings;
- the gateway mapping of `course-embed` or `course-embed-decoy`, including the provider model and
  the `course_decoy.py` hook or its seed;
- the embedding dimension;
- the chat alias;
- the `search_docs` extension (its sha256).

A record whose inputs differ from the ones in this table is not qualified.
