# S12 corpus release — from a commit to the live `study_guides` alias

A corpus release is ordinary software delivery. **One full commit SHA** determines:

- the candidate inputs (the bundle);
- the physical collection `study_guides_<SHA>`;
- the evaluation receipt;
- the Helm rollout and the alias promotion.

`study_guides` is **always a Qdrant alias**. Nothing ever writes to it as a collection.

Every release command runs from a clean, detached, exact-SHA worktree through
[`scripts/with-release.sh`](../scripts/RELEASE_WORKTREES.md). Your interactive checkout is never
reset, and generated files go to `~/releases/workbench-state/<SHA>/`, outside tracked source.

## HTTPS prerequisite for the M12 candidate

Before ingestion, verify the assigned DNS name resolves to this workspace and its existing
HTTPS endpoint answers401 anonymously and200 with the student's credentials. Keep authentication
and TLS enabled throughout rollout and rollback. The ingress smoke uses HTTPS on443 and checks
the assigned hostname and CA chain even when connecting locally with `--resolve`.
The TLS Secret, ACME account and DNS credentials are instructor-managed and must not be recreated
by a release. Monitoring probe credentials remain in their existing Kubernetes Secret.

Instructor staging rehearsal may explicitly set `CURL_CA_BUNDLE` to the official staging roots;
this does not qualify browser public trust. Never use `curl -k` or a global TLS verification bypass.
Before a live rehearsal, budget the embedding calls (currently163 chunks,3 consistency checks,
and10 evaluation queries) and the agent smoke against the actual key and shared upstream limits.
Do not start a run that cannot fit its deadline or available quota. For bounded qualification,
set `RAG_QUALIFICATION_BUDGET` and `RAG_QUALIFICATION_INTERVAL_SECONDS` to the approved
per-process call cap and minimum start interval. This switches embeddings to serial execution
with no retries (including429/5xx/timeouts), stops on the first failure, and applies to the
rendered ingestion Job and local evaluator. These controls do not change gateway quotas and
do not reserve capacity against other users. Also set `SMOKE_RATE_LIMIT_RETRIES=0`; a429 is a stop condition, not evidence of successful deployment.
Existing successful retrieval evidence may be reused only where its inputs are unchanged;
never manufacture a receipt for a new SHA or skip the release gate.

## 1. Bundle the candidate inputs (`scripts/ingest_bundle.py`)

```bash
scripts/with-release.sh <SHA> uv run --project ingestion --locked python scripts/ingest_bundle.py
```

**Input contract.** The script builds these from the exact release checkout:

| Bundled (ConfigMap `ingest-bundle-<SHA>`, mounted at `/workspace`) | Never bundled |
|---|---|
| every selected `docs/study-guides/*.md` (same selection rule as `ingestion/corpus.py`) | the course key or any credential |
| `ingestion/*.py` (ingestion source) and `ingestion/uv.lock` | tests, `.venv`, caches, anything untracked |
| `rag-settings.yaml`, `course-artifacts.yaml` | other repository files |

The bundle is **refused** (exit 1, nothing written anywhere) when any of these hold:

- the SHA is not a full 40-hex commit, or is not the checkout's `HEAD`;
- the checkout has uncommitted or untracked changes;
- the serialized ConfigMap is over **512 KiB**. The error lists the largest inputs;
- a bundled file looks like a credential (`sk-…` keys, private keys, AWS keys);
- a path contains `__`. ConfigMap keys encode `/` as `__`, and the Job maps each key back to its
  path.

**Identity.** Written to `bundle-identity.json` and to the ConfigMap's `course.dbai/*` annotations
and `course.dbai/revision` label:

| Field | Value |
|---|---|
| `revision` | the full SHA |
| `collection` | `study_guides_<SHA>` |
| `corpus_hash` | the same hash `ingestion/corpus.py` prints |
| `bundle_hash` | a hash over every bundled file |
| `image` | the qualified ingestion image digest, from `course-artifacts.yaml` |

Ingestion stores the revision and corpus hash in every point it writes.

**A new FAQ needs no image rebuild.** Commit
`docs/study-guides/session-13-defense-faq.md` and build the bundle for the new SHA. The
`revision`, `corpus_hash` and `bundle_hash` change, and the `image` digest stays the same.

**Create, never `apply`.** Put the bundle into the cluster with `kubectl create`, or
`kubectl replace --force` for a retry. Client-side `kubectl apply` copies the whole object into
the `last-applied-configuration` annotation. Annotations are capped at 256 KiB, so a
300 KB bundle fails with `metadata.annotations: Too long`. `scripts/run-ingestion.sh` does
this for you.

## 2. Retrying ingestion without harming the live corpus

The candidate for a release is `study_guides_<SHA>`. Every point stores its provenance:
revision, corpus hash, settings hash, ingestion source hash, embedding model and chunk count.
`ingestion/ingest.py` compares that stored provenance with what it is about to build, **before**
it calls the gateway:

| Target state | Stored vs planned provenance | What ingestion does |
|---|---|---|
| does not exist | — | builds it |
| exists, not live (unpromoted) | identical | recreates it (deterministic point IDs, same provenance) |
| exists, not live, same revision | **different** | **exit 1**: changed inputs under an old identity. Commit and tag a new release |
| **live** (behind an alias) | identical | **REUSED**: exit 0, no gateway call, nothing written |
| **live** | missing or **different** | **exit 1** for explicit recovery. Points and alias stay untouched |

A live collection is never reset or upserted, and neither are the previous collections kept for
rollback: ingestion writes only its own candidate. An interrupted run (Ctrl-C, killed Job, lost
gateway) leaves either no candidate or a partial one that search and evaluation refuse, because
of its point count. The next run recreates it.

**Recovery when a live candidate is refused:** do not edit or delete the live collection.
Either release a new commit/tag, which builds a new `study_guides_<SHA>`, or restore the alias to
a verified previous collection (see "Promote and restore", `scripts/promote-corpus.sh`). A change to the corpus,
settings or ingestion source always needs a **new commit and tag**. The same SHA can never mean
two different corpora.

## 3. Run the candidate ingestion Job (`scripts/run-ingestion.sh`)

```bash
cd ~/ai-workbench                                    # repo root; the helper enters the release checkout itself
scripts/with-release.sh <SHA> scripts/run-ingestion.sh <SHA>
```

The helper runs in the **release** checkout, `~/releases/workbench/<SHA>`, never in your editing
checkout. It works in a fresh non-login SSH session: without `KUBECONFIG` it falls back to the k3s
kubeconfig. It then:

1. **Builds the bundle and the Job** from [`k8s/ingest-job.yaml`](../k8s/ingest-job.yaml). The Job
   uses the pinned ingestion image, mounts the bundle at `/workspace`, reaches Qdrant at
   `http://workbench-qdrant.workbench.svc:6333`, and reads `COURSE_VIRTUAL_KEY` from the
   `workbench-keys` Secret through `secretKeyRef`. The gateway URL comes from the bundled
   `course-artifacts.yaml`. The Job has `backoffLimit: 0` and an `activeDeadlineSeconds`.
2. **Recreates** ConfigMap `ingest-bundle-<SHA>` and Job `ingest-docs-<first 12 of SHA>`. Any old
   pair for that SHA is deleted first and created again, never patched.
3. **Waits** for the Job's real result (`Complete` or `Failed`), prints the Job log and saves it,
   then returns:

| Result | Exit | Where to look |
|---|---|---|
| `Complete` and the log shows `COMPLETE candidate …` or `REUSED live candidate …` | 0 | `~/releases/workbench-state/<SHA>/ingest-job.log` |
| bundle refused (dirty checkout, over 512 KiB, secret) | 1 | the `ingest-bundle: ERROR` line; nothing reached the cluster |
| Job `Failed` (`BackoffLimitExceeded`): ingestion exited nonzero | 1 | the `ERROR:` line in the printed log, e.g. `Qdrant unreachable … is the workbench-qdrant pod Running?`, `gateway HTTP 401`, or a refused live candidate |
| Job `Failed` (`DeadlineExceeded`) or no result in time | 1 | `kubectl -n workbench describe job ingest-docs-<SHA12>`, and pod events (image pull, scheduling) |

**Retry policy.** Fix the cause (restart Qdrant, rotate the key, free capacity), then run the same
command again. The helper recreates the Job, and ingestion follows §2: it recreates an unpromoted
candidate, or reuses a live one only when the provenance matches. A candidate never becomes
"good" by editing Qdrant. A changed input needs a new commit/tag. The logs contain no key:
`ingest.py` never prints it, and gateway errors mask it.

Tune the timeout with `INGEST_TIMEOUT_SECONDS` (default 600). The Job deadline and the helper's
wait both use it.

## 4. Evaluate the candidate (`scripts/run-eval.sh`)

```bash
cd ~/ai-workbench
scripts/with-release.sh <SHA> scripts/run-eval.sh <SHA>     # release: scores study_guides_<SHA>
scripts/run-eval.sh --manual study_guides_manual            # classroom manual candidate (editing checkout)
```

The helper needs **nothing exported** in your shell, so it works from a fresh non-interactive SSH
session, like the one CI uses:

- **Key.** `COURSE_VIRTUAL_KEY` is read from the Secret `workbench/workbench-keys` into the
  helper's own environment. It is never printed. The gateway URL comes from the checkout's
  `course-artifacts.yaml`, and the query alias is always `course-embed`.
- **Forward.** It opens **its own** `kubectl port-forward` on a free localhost port chosen by the
  OS, and waits up to 20 s for Qdrant's `/healthz`. If another session is already using 6333, it
  is left alone. On success, failure, timeout or Ctrl-C the helper closes **only its own**
  forward.
- **Evaluator.** It runs `uv run --project ingestion --locked pytest evals/ -v` from the repository
  root, which is the release root in release mode. It saves `eval.log` and `eval-results.json` to
  `~/releases/workbench-state/<SHA>/`, or `…/manual/`.

| Exit | Meaning | Safe diagnostics |
|---|---|---|
| 0 | gate passed (hit@3 ≥ 0.8) | — |
| 1 | gate failed, or a missing Secret, failed forward or wrong checkout | the `[run-eval] FAILED:` line; `kubectl -n workbench get secret workbench-keys` (never `-o yaml`); `kubectl -n workbench get pods`; `eval-port-forward.log` |
| 5 | pytest collected no tests (a broken `evals/`) | `uv run --project ingestion --locked pytest evals/ --collect-only` |
| 124 | evaluation exceeded `EVAL_TIMEOUT_SECONDS` (default 600) | gateway latency or quota; retry later |
| 130 | interrupted | re-run it; nothing was promoted |

**Never** debug with `set -x`, `env` or `kubectl get secret -o yaml`: they print the key.

## 5. The evaluation receipt (`scripts/receipt.py`)

Every `run-eval.sh` run first deletes the previous `receipt.json` and `eval-results.json`. It then
writes a new receipt for a **passing or failing** evaluation, to
`~/releases/workbench-state/<SHA>/receipt.json` (or `…/manual/`). That location is outside tracked
source, so the release checkout stays clean. An aborted run (no Secret, failed forward) leaves
**no** receipt. Promotion accepts nothing else.

**Schema `dbai/rag-receipt/v1`: fields and where they come from**

| Field | Source |
|---|---|
| `mode`, `revision`, `candidate` | the request: release `<SHA>` / `study_guides_<SHA>`, or manual checkout revision / candidate name |
| `stored_revision`, `corpus_hash`, `settings_hash`, `ingestion_source_hash`, `ingestion_model`, `points` | the **evaluated candidate's stored provenance**, from `eval-results.json` |
| `query_model`, `k`, `threshold`, `required`, `hits`, `total`, `score`, `passed` | the evaluator result |
| `image` | release: the ingestion image digest from `bundle-identity.json`; manual: "local uv environment" |
| `eval_results_sha256` | the hash of `eval-results.json` when the receipt was made |
| `created_utc` | time of the evaluation |

**Verification.** `deploy.sh` and `promote-corpus.sh` run it before any Helm or alias change:

```bash
scripts/with-release.sh <SHA> uv run --project ingestion --locked python scripts/receipt.py \
    verify --state ~/releases/workbench-state/<SHA> --sha <SHA> [--qdrant-url http://127.0.0.1:<port>]
```

A receipt is **rejected**, with a specific reason and exit 1, when:

- it is missing, is not valid JSON, or has the wrong schema;
- the evaluation failed, or its `hits`/`total`/`required`/`passed` do not agree, or its gate is
  weaker than hit@3 ≥ 0.8;
- its `mode`, `revision` or `candidate` differ from the request, or the candidate was built from
  another revision;
- the corpus, settings, ingestion source, ingestion alias or query alias it records differ from
  what the checkout contains **now** (stale evidence);
- the image differs from the qualified pin;
- `eval-results.json` changed after the receipt was made;
- with `--qdrant-url`: the stored candidate no longer exists, or its provenance or point count
  differs.

**Getting fresh valid evidence.** Never edit a receipt. Re-run the evaluation for the exact
revision you want to promote. If the inputs changed, commit, tag, re-ingest and re-evaluate the new
SHA:

```bash
scripts/with-release.sh <SHA> scripts/run-ingestion.sh <SHA>
scripts/with-release.sh <SHA> scripts/run-eval.sh <SHA>
```

## 6. One production writer at a time (`scripts/production-lock.sh`)

Production is the Helm release `workbench` **plus** the live `study_guides` alias. Two entry points
change it: the Actions deploy (`scripts/deploy.sh` over SSH) and a classroom shell
(`scripts/promote-corpus.sh`). GitHub's `concurrency: workbench-production` serializes Actions
runs only. It cannot see your shell. So every production mutation also takes **one kernel lock on
the VM**, `~/releases/workbench-state/production.lock`, which lives outside every checkout.

- **Scope.** The lock is held from before the Helm upgrade until the alias is switched. That
  includes a `--atomic` Helm rollback or an alias restore after a failed smoke check. Child
  processes inherit it, so no second operation can start until the whole transition and its
  recovery have ended.
- **Waiting is visible.** A second operation prints
  `[production-lock] BUSY — waiting up to 900s. Current holder: <label> | pid | host | since`, then
  runs after the first one finishes. After `WB_LOCK_WAIT_SECONDS` (default 900) it stops with
  **exit 75** `GAVE UP … production is still busy; nothing was changed`. Re-run it later.
- **No permanent block.** The kernel releases the lock the moment the holder exits, even when it
  is killed or its SSH session drops. The `production.lock.holder` file is informational only:
  after a crash it may name a dead process while the lock is already free.

**Recovery after an interrupted release.** A dropped SSH session, a canceled run or a `kill -9`
during `helm upgrade` leaves Helm in `pending-upgrade`, and the next release then fails with
`another operation (install/upgrade/rollback) is in progress`. Nothing changes silently. Run:

```bash
scripts/recover-production.sh
```

It takes the same lock. It rolls a `pending-*` release back to the last deployed revision, or
uninstalls a first install that never finished. It then prints the Helm history, the images
running and the live alias. Compare those with the last good receipt, then release again.

**GitHub Actions queueing.** With `cancel-in-progress: false`, an **in-progress** production run
is never canceled. But a concurrency group keeps at most **one pending** run. When a third release
tag arrives while one run is running and another is pending, the older **pending** run is
**canceled** and shows as "canceled" / "superseded" in the Actions list. Queued runs are therefore
**not** guaranteed to run in FIFO order, or at all. After tagging several releases quickly:

1. Open the Actions list and look for canceled `workbench-deploy` runs.
2. Check which SHA is actually live (the receipt, `helm history`, the alias).
3. If the release you wanted was canceled, **release it again**: push a new `deploy-*` tag on
   that commit, or re-run that workflow.

## 7. Promote and restore the live alias (`scripts/promote-corpus.sh`)

**Alias versus physical collection.** `study_guides_<SHA>` (or `study_guides_manual`) is a
**physical collection**: real points written by ingestion, immutable once live. `study_guides` is
only an **alias**, a name pointing at one physical collection. The `search_docs` tool and users
always read the alias. Promotion moves the name. It never copies, rewrites or deletes points.

```bash
scripts/with-release.sh <SHA> scripts/promote-corpus.sh <SHA>   # release (deploy.sh calls this for you)
scripts/promote-corpus.sh --manual study_guides_manual         # classroom manual candidate
scripts/promote-corpus.sh --restore study_guides_<old-SHA>     # point the alias back at a previous release
```

Under the production lock, the helper opens its own Qdrant forward and then:

1. **Checks the receipt.** `receipt.py verify` runs, including the stored candidate. A missing,
   failing, stale or tampered receipt stops the helper with `receipt rejected — the live alias was
   not touched`.
2. **Switches the alias in one atomic request.** Qdrant receives `delete_alias` + `create_alias`
   in a single call, so readers see the old target or the new one, never a missing alias. The
   **first** promotion simply creates `study_guides`.
3. **Verifies the result.** The alias must point at the candidate, and that collection must be
   complete.
4. **Restores on failure.** Any failure after the switch puts the alias back on the previous
   target. A failed first promotion removes the alias it created. Either way the helper exits
   nonzero. If even the restore fails, it says so (`COULD NOT RESTORE`) and names the recovery
   commands.
5. **Records the promotion.** `promotion.json` (previous → new, receipt hash, status) goes to the
   state dir, and a JSON line to `~/releases/workbench-state/promotions.log`.

**Restore boundaries.** `--restore` accepts only a collection that `promotions.log` shows was
promoted before, so an unevaluated collection can never be made live this way. The **previous
collection is always kept**: rollback depends on it.

**Cleanup is explicit and separate.** It never happens during a release or a failure drill:

```bash
# only collections that are NOT live and NOT the most recent previous release:
curl -s -X DELETE http://127.0.0.1:<forward-port>/collections/study_guides_<old-SHA>
```

*Drill hook (instructor only).* Setting `WB_FAULT_INJECT=alias-verify` makes the post-switch
verification fail on purpose, so you can watch the restore path: the previous alias comes back, or
the alias disappears again on a first release. Never set it in a real release.

## 8. One recoverable release: Helm plus corpus (`scripts/deploy.sh`)

```bash
scripts/with-release.sh <SHA> scripts/deploy.sh      # what the deploy job runs, after ingest and retrieval-eval
```

Under the production lock, `deploy.sh` runs four steps in order. Any failure after step 2 undoes
**both** halves:

| Step | On failure |
|---|---|
| 1. **Receipt gate.** `receipt.py verify` for this SHA, including the stored candidate | exit 1. No Helm rollout, no alias change |
| 2. **Helm.** `helm upgrade --install --atomic --wait --timeout 3m` with `my-values.yaml` | exit 1. `--atomic` keeps or restores the previous revision; the alias is **not** promoted |
| 3. **Alias.** `promote-corpus.sh <SHA>` (atomic) | the helper restores the alias, then `deploy.sh` rolls Helm back to the previous revision, or uninstalls a failed first release |
| 4. **Smoke.** Authenticated `GET /api/health` through the Traefik ingress (credentials from the S10 probe Secret `monitoring/workbench-probe-auth`), then the **deployed agent** answers a golden question. It must make a successful `search_docs` call whose passages come from **this** SHA's corpus | the previous alias **and** the previous Helm revision are restored. For a first release, the install is removed and no alias remains |

`release-record.json`, in the state dir, records the SHA, the status (`deployed`, `rejected`,
`helm-failed`, `promote-failed` or `smoke-failed`), the previous and new Helm revisions, the
previous and new alias targets, and the images running. Previous collections are never deleted.
If the compensation itself fails, the helper prints `COMPENSATION FAILED`. Then run
`scripts/recover-production.sh`, followed by `scripts/promote-corpus.sh --restore <previous>`,
and compare with the last good record.

**Old tags run their own helpers.** `with-release.sh` executes the scripts *at the release SHA*.
Re-running a tag made before this S12 tooling existed runs the S9 `deploy.sh`, which has no
receipt gate and no alias step, and which wrote its record to `receipt.json`. Re-release old
content on a new commit instead of re-running a pre-S12 tag.

**Gateway rate limit during the smoke.** The course key allows a limited number of requests per
minute, and the release's own ingestion has just used many of them. When the smoke's agent run
fails **only** because the gateway answered HTTP 429, `smoke_release.py` waits for the key's window
to reset (the gateway's `Limit resets at` time, at most 65 s, otherwise 20/40/60 s) and tries again,
up to 3 more times. Any other smoke failure is final at once, and the release is compensated as above.

## 9. Classroom manual candidate (manual mode) versus release (SHA mode)

| | **Manual mode** (S12 Part A/B, local practice) | **SHA mode** (release gate, Actions or `with-release`) |
|---|---|---|
| where | your editing checkout, repository root | the clean release checkout `~/releases/workbench/<SHA>` |
| candidate | `study_guides_manual` (a new name for each changed corpus) | `study_guides_<SHA>`, built by the Job |
| evidence | `~/releases/workbench-state/manual/receipt.json`, bound to your checkout's current revision (`+dirty` allowed) and corpus | `~/releases/workbench-state/<SHA>/receipt.json` |
| promotion | `./scripts/promote-corpus.sh --manual <candidate>` | `scripts/deploy.sh` (Helm + alias + smoke) |

Both modes use the same receipt verification, the same atomic alias switch and restore, and the same
production lock. A manual promotion **waits** while a release is running.

Rehearsed classroom sequence, run from `~/ai-workbench`:

```bash
kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333 &            # for ingest/search
export COURSE_VIRTUAL_KEY="$(kubectl -n workbench get secret workbench-keys -o jsonpath='{.data.COURSE_VIRTUAL_KEY}' | base64 -d)"
uv sync --project ingestion --locked
uv run --project ingestion --locked python ingestion/ingest.py --docs docs/study-guides --collection study_guides_manual
uv run --project ingestion --locked python ingestion/search.py "What is infrastructure as code?" --collection study_guides_manual
./scripts/run-eval.sh --manual study_guides_manual                             # hit@3 >= 0.8 -> receipt
./scripts/promote-corpus.sh --manual study_guides_manual                       # atomic: study_guides -> study_guides_manual
# my-values.yaml: extensions.search_docs.enabled: true   then:
helm upgrade workbench ./charts/ai-workbench -n workbench -f my-values.yaml --atomic --wait
```

Now ask a course question in the UI. Open the `search_docs` card to see the cited
`docs/study-guides/...` passages.

- **Changing the corpus afterwards.** Edit, then evaluate a **new** candidate such as
  `study_guides_manual_2`: the live manual candidate is immutable and ingestion refuses to touch
  it. The old receipt is rejected as stale (`corpus_hash … != this checkout`).
- **Back to the release.** `./scripts/promote-corpus.sh --restore study_guides_<SHA>`.
- **One receipt at a time.** The manual receipt always belongs to the **last** manual evaluation.
  Evaluate the candidate you are about to promote, then promote it.

## 10. The release gate in CI: `ingest → retrieval-eval → deploy`

Your `.github/workflows/deploy.yml` triggers **only** on `deploy-*` tags. It runs three jobs, each
chained to the previous one with `needs:`. Each job passes the same full `RELEASE_SHA`
(`github.sha` of the tag) through the ssh-action `envs:` boundary, and enters the exact release
checkout with `scripts/with-release.sh`:

```text
ingest          scripts/with-release.sh "$RELEASE_SHA" scripts/run-ingestion.sh "$RELEASE_SHA"
retrieval-eval  scripts/with-release.sh "$RELEASE_SHA" scripts/run-eval.sh "$RELEASE_SHA"      (needs: ingest)
deploy          scripts/with-release.sh "$RELEASE_SHA" scripts/deploy.sh                       (needs: retrieval-eval)
```

- **Concurrency.** `concurrency: workbench-production` with `cancel-in-progress: false`. On the VM,
  the production lock (§6) also serializes the deploy against classroom shells.
- **A red job stops the graph.** A failed ingestion or evaluation means **deploy is skipped**, and the
  live alias and Helm revision stay exactly as they were. A failed deploy compensates itself
  (§8).
- **Rerunning an old tag** (re-run its workflow run) uses that tag's original SHA: its source,
  its helpers and its candidate `study_guides_<old-SHA>`. It deploys that old release again. Your
  editing checkout on the VM is never reset. Rehearsed: a re-run of an earlier tag redeployed its
  163-point corpus. Re-running the latest tag then restored the FAQ release.
- **This is a release gate, not a pull-request check.** The workbench has no branch protection or
  required PR checks. What protects production is that only a green `retrieval-eval` for the same
  SHA lets `deploy` run.

## 11. Drill: embedding sabotage on an immutable tag (instructor fixture)

1. **Baseline.** Release a known-good tag and record `helm history`, the alias target, and the
   live point count plus a content hash (`evidence/s12/`).
2. **Sabotage.** Change **only** `rag-settings.yaml`: `embedding_model: course-embed-decoy`.
   Commit, tag and push. Expected: `ingest` is **green**, because the decoy has the same 4096
   dimensions, so the candidate `study_guides_<bad-SHA>` is built. `retrieval-eval` is **red**,
   because queries always use `course-embed` and the gate needs ≥ 0.8. `deploy` is **skipped**.
   The live alias, Helm revision and point identity are **unchanged**.
3. **Repair.** Revert the setting in a **new commit**, tag it, push it. All three jobs go green and
   the new candidate is promoted.
4. **Immutability.** Re-run the **bad** tag's workflow. It uses the bad input again and is red
   again. A tag can only be repaired by a new release, never by editing live data.

The score is only "below 0.8". The rehearsal gave 2/10, but other corpora and questions score
differently. **Diagnosis:** the receipt and the `eval.log` header show
`ingested with 'course-embed-decoy', queried with 'course-embed'`. Equal dimensions, so this is
not a dimension error; the vectors live in different spaces. **Never** "fix" the drill by
touching the live collection.

## 12. Drill: new FAQ reaches retrieval only through a release

1. Ask the workbench about the Session 13 defense format and open the `search_docs` card. It
   cites no `session-13` file. The model may answer from general knowledge or, as in the
   rehearsal, say it cannot find the answer. Neither outcome proves freshness. The **tool card's
   sources** do.
2. Add `docs/study-guides/session-13-defense-faq.md` with the policy: every student submits a
   4-minute recorded demo; about 10 randomly selected students defend live; each student
   reviews two recordings. Commit and push `main` **without a tag**. No workflow runs, and the
   live alias, point count and corpus identity are unchanged. The same question still cites no
   FAQ.
3. Tag `deploy-12.N` and push it. The Job's bundle now has 13 documents and a new corpus hash, on
   the **same** ingestion image digest. The evaluation passes, the candidate is promoted, and
   the answer now cites `docs/study-guides/session-13-defense-faq.md` with the four-minute,
   about-ten and two-reviews facts.
4. Record the old and new SHA, the corpus hash, the alias target and the cited source in
   `evidence/s12/`. Keep every earlier file and piece of evidence.
5. **Homework follow-up.** Append golden entries that only the new FAQ can answer, keeping q01–q10
   (`docs/CORPUS.md`). Release again and show the gate green on the expanded set.

> **Gateway finding (2026-09-25).** The course gateway returned **batched** embeddings in the wrong
> order when a batch mixed cached and new texts. After the FAQ release, 10 of 165 live vectors
> belonged to neighbouring chunks, and the FAQ was unretrievable even though the gate was green.
> Ingestion now sends **one text per request**, 4 in parallel, retries rate limits, and
> re-embeds 3 random chunks before writing anything. The fixed release had 0 of 165 misaligned
> vectors and cited the FAQ.
> The root cause is upstream at nan.builders (batched responses are wrong on partial cache hits).
> The course gateway now splits every nan.builders embedding batch itself (`nan-split` provider,
> y0-stack-litellm@5f8e6a0). The single-text client behaviour stays as defense in depth.
