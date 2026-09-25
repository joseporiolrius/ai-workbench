---
title: "Session 12 — LLMOps: RAG as Deterministic Software"
session: 12
source: "oriolrius/esade-devops:backlog/docs/doc-14 - Session-12-LLMOps-RAG.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 12 — LLMOps: RAG as Deterministic Software

Session 12 fills the workbench's Qdrant instance with the course's own study-guide corpus, deploys an agentic `search_docs` retrieval tool into pi-web-ui, and wires a golden-set retrieval evaluation into CI as a release gate — the same "evaluate → assert threshold → exit code → pipeline blocks" pattern Session 11 taught for the overheat model. No new infrastructure appears this week: uv, Docker, kubectl, Helm, GitHub Actions, Qdrant, the course gateway, and pytest were all introduced earlier and now compose.

## RAG's two phases and why the embedding model must match

RAG has an offline indexing phase (chunk documents → embed via the central gateway → upsert into Qdrant) and an online query phase (embed the question → similarity search → augment the prompt). Know cold: the embedding model must be identical in both phases, because vectors from different models occupy incompatible spaces — this is failure mode #2 of six: bad chunking (fix: semantic chunking/overlap), embedding mismatch (fix: pin/version the model), wrong tool description (fix: iterate on it), stale index (fix: scheduled re-ingest), top-k too low/high (fix: tune k, rerank), no citations (fix: return source metadata, prompt to cite).

## Agentic retrieval and MCP

Agentic retrieval means the LLM decides, per turn, whether to call the `search_docs` tool based on its name and description — a tool call the model may or may not make, not a fixed pipeline stage; a bad tool description causes missing or spurious retrieval. MCP (Model Context Protocol) standardizes one protocol between AI hosts/clients and tool servers, turning M clients × N tools into M+N, via two JSON-RPC calls: `tools/list` (discover) and `tools/call` (invoke with JSON-Schema arguments). Nobody writes TypeScript — students deploy a pinned `search_docs` extension into pi-web-ui via ConfigMap and `helm upgrade`, then verify the tool-call trace and cited answer in the UI.

## Ingestion pipeline, the golden-set eval, and the Kubernetes Job

The `ai-workbench` repo's `ingestion/` (from `starter-s12-v1.0.0`) holds a readable, ~80-line `ingest.py` (documents → chunks → course-gateway embeddings → Qdrant upsert) — not a framework like LangChain or Haystack. `rag-settings.yaml` pins `embedding_model: course-embed`, chunk settings, and `top_k: 3`. Students run ingestion against a candidate collection (`study_guides_manual`, not the live alias), then check `evals/golden_set.yaml` — ten question → expected-source pairs — with `./scripts/run-eval.sh --manual study_guides_manual`, running `pytest evals/ -v`, requiring hit@3 ≥ 0.8 (at least 8 of 10); failures exit nonzero. Promotion to the live `study_guides` alias happens only via `./scripts/promote-corpus.sh`, which checks the local receipt against the evaluated inputs and flips Qdrant's alias atomically — practice and release stay separate; no untested alias change is allowed. In production, `k8s/ingest-job.yaml` receives `QDRANT_URL` via service DNS and `COURSE_VIRTUAL_KEY` via Secret; the tagged checkout's source, settings, and corpus mount from a generated ConfigMap (capped 512 KiB), so a new study guide needs no image rebuild. Ingestion is a Job, not a Deployment, because it is a finite batch task — a Deployment would keep restarting the "finished" container. `./scripts/run-ingestion.sh <full-SHA>` creates `ingest-docs-<short-SHA>`, waits for completion, fails on a failed Job, and writes to isolated collection `study_guides_<full-SHA>` — never touching the live alias.

## The CI release gate: ingest → retrieval-eval → deploy

`.github/workflows/deploy.yml` gains a required dependency chain triggered only on `deploy-*` tags, serialized with concurrency group `workbench-production`: `ingest` (`run-ingestion.sh`) must succeed before `retrieval-eval` (`run-eval.sh`), which must pass before `deploy` (`deploy.sh`). `run-eval.sh` opens its own port-forward, reads the course key from the Secret, and writes a receipt (score, threshold, SHA, corpus hash, candidate, model aliases, image digest); `deploy.sh` validates the receipt, applies Helm with `--atomic --wait --timeout 3m`, then promotes the candidate via the atomic alias helper — a failed promotion restores the previous alias and revision. A bad candidate never replaces the live index; this is a release gate, not a branch-protection PR check.

## The two drills: embedding sabotage and the stale index

The embedding-sabotage drill switches only `rag-settings.yaml`'s ingestion alias to a decoy embedding model (`course-embed-decoy`) sharing vector dimensions but occupying an incompatible space; the candidate's hit@3 falls below 0.8, deploy is skipped, and the live alias stays untouched — reverting the setting and re-tagging restores a green promotion. The stale-index drill pushes a new document to `docs/study-guides/` **without a tag** first, so the live alias still points at the prior release and the workbench cannot yet answer from the new file; only tagging a new `deploy-*` release makes the Job pick it up, evaluate, and promote it. In the drill the student adds `docs/study-guides/session-13-defense-faq.md`; the initial corpus deliberately does not contain it, so its answer can only become citable through the tagged-release / ingest / evaluate / promote cycle.

## Boardroom angle and the DIY-vs-managed question

The Air Canada case (Moffatt v. Air Canada, February 2024) frames the stakes: its support chatbot invented a bereavement-fare policy, and a tribunal held the airline to it — "the chatbot said it" is not a defense. RAG grounds answers in real documents, but ungoverned RAG fails *confidently*: wrong chunk, stale index, or mismatched embeddings produce fluent, cited-looking nonsense — grounding without evaluation just adds credibility to errors. Retrieval is measurable: a fixed golden set gives a hit rate, a hit rate becomes a threshold, a threshold becomes a CI gate, exactly like Session 11's accuracy gate. The closing discussion contrasts this DIY stack against a managed product like Gemini File Search: what you buy (chunking, embeddings, re-indexing, citations) versus what you give up (model choice, data locality, eval control, cost transparency).

## Common failure modes to diagnose

If an "optimized" ingestion pipeline scores far below its gate with no runtime errors, suspect embedding mismatch — check whether ingestion and query use the same embedding alias. If a user reports the workbench doesn't know a document added yesterday, suspect a stale index — the file exists in git but was never embedded and upserted; fix by re-running ingest → evaluate → promote via a new tag, not by assuming hallucination.
