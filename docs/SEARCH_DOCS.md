# `search_docs` — model-selected course retrieval in pi-web-ui (S12)

`search_docs` is a pi agent **extension**, a tool that the chat model may call.
It ships with the course chart:

- **Source:** `charts/ai-workbench/extensions/search-docs/index.ts`.
- **Pin:** its sha256 is recorded in `course-artifacts.yaml` (`id: retrieval-extension-search-docs`)
  and in the ConfigMap annotation `course.dbai/extension-sha256`.
- **Mount:** the chart mounts it at `$PI_CODING_AGENT_DIR/extensions/search-docs/`, where
  pi-web-ui's agent SDK (pi 0.85.1) loads it at session start. There is no build step and no
  image change.

You enable it with values only:

```yaml
# my-values.yaml
extensions:
  search_docs:
    enabled: true
    collection: study_guides   # the LIVE alias, promoted by scripts/promote-corpus.sh
    topK: 3
```

```bash
helm upgrade workbench ./charts/ai-workbench -n workbench -f my-values.yaml --atomic --wait
```

## What happens on a question

1. **Tool decision.** pi sends your message plus the tool definitions to `course-chat`, and the
   **model** decides whether to call `search_docs`. Course questions usually trigger it. General
   questions ("What is the capital of Australia?") are answered directly, with **no** tool call.
2. **Search.** `search_docs` runs **server-side** in the pi-web-ui pod. It embeds the query
   through the course gateway with the fixed alias **`course-embed`**, using `COURSE_VIRTUAL_KEY`
   from the `workbench-keys` Secret. It then queries Qdrant `http://workbench-qdrant:6333` through
   the alias `study_guides`. The browser never sees the key or talks to the gateway; it only
   reaches the UI through Traefik basic-auth.
3. **Answer.** The tool returns the top `topK` passages, each labelled
   `[n] docs/study-guides/<file>.md § <section> (score)`. The model answers and cites those
   paths.

In the UI each call is a collapsible **tool card** showing the arguments (`query`), the
returned passages and the duration. That card is your trace: model → tool → source → answer.
Qualified example: *"In this DevOps course, why must the Terraform state file never be
committed to Git?"* → `search_docs` → `docs/study-guides/session-06-terraform-iac.md § State:
what it is and why it is never committed` → an answer citing that path.

A question answered **without** a tool call is not a failure. It means the model judged
retrieval unnecessary. Judge the answer, not the absence of a card.

## Diagnosing

| Symptom | Likely cause | Check |
|---|---|---|
| No `search_docs` card on course questions (the model can only answer from general knowledge) | extension not enabled or not mounted | `helm get values workbench -n workbench` shows `extensions.search_docs.enabled: true`; `kubectl -n workbench get cm workbench-search-docs`; `kubectl -n workbench exec deploy/workbench-pi-web-ui -- ls /app/.pi-config/extensions/search-docs` |
| Red tool card: `Qdrant collection/alias 'study_guides' returned HTTP 404` | the live alias does not exist (nothing promoted yet, or a wrong `collection` value) | `curl -s localhost:6333/aliases` through a port-forward; promote an evaluated candidate |
| Red tool card: `gateway embeddings (course-embed) returned HTTP 401/403/429` | key missing, wrong or out of budget | `kubectl -n workbench get secret workbench-keys`; check your spend. Error text masks the key |
| Red tool card: `COURSE_VIRTUAL_KEY is not set in the UI container` | Secret key name wrong | the Secret must have the key `COURSE_VIRTUAL_KEY` |
| The model answers "I can't answer reliably" | retrieval failed; the model says so instead of guessing | open the red card to read the error |

Tool errors are **thrown**, so the card turns red and the model is told that retrieval failed.
No error message contains the course key.

## Homework exercise: `topK: 1`

Set `extensions.search_docs.topK: 1`, `helm upgrade`, and ask three golden-set questions. Record
the answer, the citation and the number of `search_docs` calls, then restore `topK: 3` and
upgrade again. Do **not** expect every answer to degrade. In the instructor run (three golden
questions: S10 individual charts, S8 liveness vs readiness, S11 local `mlruns`), all three
answers stayed correct with `topK: 1`. The model compensated by searching more often: 4, 1 and 7
calls, compared with 2, 1 and 2 at `topK: 3`. Degradation shows up when the needed fact is spread
over several chunks, or when the best chunk is not the first hit. Write down which failure mode
you simulated (top-k too low).

## Requalification

Any change to the extension source (its sha256), the chat alias, the embedding mapping or the
Qdrant schema requires re-running the cited-answer and no-tool checks, and updating the manifest
record.
