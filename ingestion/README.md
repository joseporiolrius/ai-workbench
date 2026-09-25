# `ingestion/` — readable study-guide ingestion and search (S12)

```text
docs/study-guides/*.md ──chunk──► course gateway /embeddings ──► Qdrant candidate collection
                                   (rag-settings.yaml alias)      study_guides_manual | study_guides_<SHA>
```

| File | What it does |
|---|---|
| `ingest.py` | Validates the inputs, chunks them, embeds **every** chunk, then recreates the candidate and upserts. Prints `COMPLETE` only when Qdrant holds exactly the planned points. |
| `search.py` | Smoke search that prints cited results. The question is always embedded with `course-embed`. |
| `rag.py` | Shared helpers used by both scripts and by the evaluator: settings, chunker, gateway client, Qdrant REST client and write protection. |
| `corpus.py` | Corpus selection, corpus hash and golden-set validation (see [`docs/CORPUS.md`](../docs/CORPUS.md)). |
| `pyproject.toml`, `uv.lock` | The locked uv project (Python 3.12, httpx, PyYAML, pytest). |
| `tests/` | Offline tests (`uv run --project ingestion --locked pytest ingestion/tests`). |

## Run it from the repository root

Every command starts in `~/ai-workbench`, **not** in `ingestion/`. `--project ingestion` only
selects the uv environment; `docs/…`, `rag-settings.yaml` and `course-artifacts.yaml` still
resolve from the root. Never leave a `cd ingestion` in your shell, because later Helm and eval
commands expect the root.

```bash
cd ~/ai-workbench
uv sync --project ingestion --locked
kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333 &    # QDRANT_URL defaults to http://127.0.0.1:6333
uv run --project ingestion --locked python ingestion/ingest.py \
    --docs docs/study-guides --collection study_guides_manual
uv run --project ingestion --locked python ingestion/search.py \
    "What is infrastructure as code?" --collection study_guides_manual
```

`ingest.py` prints the corpus hash, the Git revision (`<SHA>`, plus `+dirty` when the corpus,
settings or ingestion code have uncommitted changes) and the final point count. `search.py`
prints the collection's provenance, then the top `top_k` hits. Each hit has a score, a citation
`docs/study-guides/<file>.md § <section>` and a snippet.

## Evaluate a candidate: `evals/`

```bash
QDRANT_COLLECTION=study_guides_manual EVAL_RESULTS=/tmp/eval.json \
    uv run --project ingestion --locked pytest evals/ -v
```

`evals/test_retrieval.py` embeds each question in `evals/golden_set.yaml` with **`course-embed`**.
That alias is fixed by the contract and ignores `rag-settings.yaml`. It then searches the
candidate named in `QDRANT_COLLECTION` and checks whether the expected guide is in the top
`k` (3). In `-v` mode each question shows as `PASSED` (hit) or `XFAIL` (miss, with the files
retrieved instead), so a single miss does not fail the run. `test_retrieval_gate` decides the
exit code, and the summary prints `hit@3 = hits/total = score (threshold 0.8: need N) -> PASS|FAIL`.

- **The threshold is a fraction.** Ten questions need 8 hits and fifteen need 12, computed
  exactly, without float drift. A golden set may be stricter than hit@3 ≥ 0.8 but never
  weaker (`k > 3` or `threshold < 0.8` fails).
- **Nothing that goes wrong can produce a pass.** A missing key, a missing or unknown
  collection, an incomplete candidate, an unreachable Qdrant or gateway, a rejected key, or a
  malformed or empty golden set all fail. Zero collected tests exit 5.
- **`EVAL_RESULTS` receives nonsecret JSON** for the release receipt: the candidate and its
  provenance, the query model, k, threshold, required, hits, total, score and passed, and for
  each question the rank and the retrieved sources.

## Settings: `rag-settings.yaml`

| Key | Meaning |
|---|---|
| `embedding_model` | Gateway alias used to embed **the documents** (default `course-embed`). The S12 decoy drill sets it to `course-embed-decoy`, and ingestion honours it. |
| `collection_prefix` | `study_guides`: the live **alias** name. Candidates are named `study_guides_<suffix>`. |
| `chunk_size`, `chunk_overlap` | Characters per chunk (200–4000, heading prefix included) and characters repeated between consecutive chunks of one section (0 to half of `chunk_size`). |
| `top_k` | Results per query: 3. |

Unknown keys, missing keys or out-of-range values stop ingestion before it contacts any service.
The **query** alias is not a setting. `search.py`, the evaluator and `search_docs` always use
`course-embed` from `course-artifacts.yaml › retrieval`, so a bad ingestion alias shows up as a
failed evaluation instead of hiding itself.

## What a point stores

`text` (the chunk, prefixed with `<guide title> — <section>`), `source` (the citation path),
`section`, `title`, `chunk_index` and `citation`. Provenance fields are also stored:
`corpus_hash`, `corpus_revision`, `corpus_chunks`, `embedding_model`, `source_sha256`,
`settings_hash` and `ingestion_source_hash`. Point IDs are deterministic
(`uuid5(source#chunk_index)`), so the same inputs give the same points.

## What ingestion refuses to do

- **It never writes the live alias `study_guides`.** Make a candidate and promote it with
  `scripts/promote-corpus.sh`.
- **It never rewrites the collection the alias currently points to.** A live candidate is
  immutable.
- **It never writes `monitoring_demo`**, the S10 monitoring fixture, or anything not named
  `study_guides_<suffix>`.

## Embedding requests

`rag.embed()` sends **one text per request** (4 in parallel) and returns vectors in input order.
It never batches, because the course gateway returned batched embeddings **misordered** when a batch
mixed cached and uncached texts. Rate limits (HTTP 429 that is not a budget error) are retried
with backoff. Before writing anything, `ingest.py` re-embeds 3 random chunks and refuses a
candidate whose vectors do not match their own text.

## Failures and partial candidates

Every failure prints `ERROR: …` and exits **1**. The order of the steps limits the damage:

1. Settings, corpus, retrieval contract and key are validated first. A bad source or bad
   settings touch nothing.
2. The protection check and a Qdrant reachability check run before any gateway call.
3. **All** embeddings are computed before the first Qdrant write. A gateway failure leaves
   Qdrant untouched: that covers a bad key (401), an alias the key may not use (403), an
   exhausted budget (429) and an unreachable gateway. Timeouts and 5xx responses are retried
   twice.
4. A dimension different from the contract (4096) is rejected. That is a different fault from
   the decoy.
5. If Qdrant fails after the candidate was created, ingestion deletes the partial collection.
   If even that fails, it prints a warning that the collection is **not** a complete candidate.

Every point carries `corpus_chunks`, so `search.py` (and the evaluator) refuse any collection
whose exact point count differs: `collection … is INCOMPLETE (123 points, expected 163)`. Re-run
ingestion to recreate an unpromoted candidate.

## Secrets

The only credential is the course virtual key in the environment variable `COURSE_VIRTUAL_KEY`.
The scripts send it only as the gateway's `Authorization` header. They never print it, write it
to a payload or log it, and a gateway error message has any echoed key masked. Load it without
echoing it:

```bash
# On the VM, from the existing Kubernetes Secret (prints nothing):
export COURSE_VIRTUAL_KEY="$(kubectl -n workbench get secret workbench-keys -o jsonpath='{.data.COURSE_VIRTUAL_KEY}' | base64 -d)"
# Or type it without echo:
read -rsp "Course key: " COURSE_VIRTUAL_KEY && export COURSE_VIRTUAL_KEY
```

Never commit it, never paste it into `rag-settings.yaml`, the corpus or evidence, and keep it out
of screenshots. Optional overrides: `QDRANT_URL`, `QDRANT_API_KEY` and `COURSE_GATEWAY_URL`
(default from `course-artifacts.yaml`).
