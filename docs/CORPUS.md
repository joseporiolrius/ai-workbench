# Study-guide corpus and golden set (S12)

This README describes the retrieval corpus in `docs/study-guides/` and the questions in
`evals/golden_set.yaml`. It sits outside `docs/study-guides/` on purpose: only the files
inside that directory are ingested. Run every command from the **ai-workbench repository root**.

## What is in the corpus

The corpus holds one English study guide per course session, S1 to S12. Each guide is
derived from the course source document named in its front matter:

```yaml
---
title: "Session 06 — Infrastructure as Code"
session: 6
source: "oriolrius/esade-devops:backlog/docs/doc-8 - Session-06-Terraform-IaC.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d   # course-docs commit it reflects
---
```

**Selection rule:** every `*.md` file directly inside `docs/study-guides/` is part of the corpus.
Subdirectories and files elsewhere, including this README, are not ingested.

## Citation paths

A chunk is cited by the **repository-root-relative path** of its file, for example
`docs/study-guides/session-06-terraform-iac.md`. That same string is:

- the `source` payload that ingestion stores with every chunk;
- the value that `search.py` and the `search_docs` tool print as the citation;
- the `expected_source` of a golden-set entry.

Renaming a guide changes its citation. Update every golden entry that points to it in the same
commit, otherwise validation fails.

## Corpus identity (revision and content hash)

A corpus is identified in two ways:

- **Revision:** the Git commit of this repository. Release candidates are named after it
  (`study_guides_<full-SHA>`).
- **Content:** the corpus hash, which is SHA-256 over a `sha256sum`-style manifest of the
  selected files, sorted by path. It changes when any file's content changes, and when a file
  is added, removed or renamed. It does not depend on timestamps or on the machine.

```bash
uv run --project ingestion --locked python ingestion/corpus.py \
    --docs docs/study-guides --golden evals/golden_set.yaml
# Reproduce the hash without Python:
sha256sum docs/study-guides/*.md | LC_ALL=C sort -k2 | sha256sum
```

Ingestion records both identities in every point payload, and the evaluation receipt records
them too. That lets you prove which corpus a live answer came from.

## The golden set

`evals/golden_set.yaml` holds ten question-to-expected-source pairs:

```yaml
version: 1
threshold: 0.8        # pass when hit@k / questions >= threshold
k: 3                  # the expected file must appear in the top k results
questions:
  - id: q01
    question: "..."
    expected_source: docs/study-guides/session-06-terraform-iac.md
```

Validation (`ingestion/corpus.py`, and the evaluator before it scores anything) fails with a
nonzero exit if any of these hold:

- the file is not valid YAML, or it is not a mapping;
- a top-level key or an entry key is unknown;
- an entry is not a mapping, or its `id`, `question` or `expected_source` is missing or empty;
- two entries share an `id`, or ask the same question (compared case- and space-insensitively);
- an `expected_source` is not a file in the selected corpus;
- there are fewer than 10 entries, `threshold` is not in (0, 1], or `k` is not a positive integer.

## Adding your five questions (S12 homework)

1. Pick five study guides or sections that the professor's ten questions do not touch.
2. **Append** five entries after `q10`, with new ids (for example `s01`–`s05`) and questions
   distinct from the existing ones. Never edit or delete `q01`–`q10`: they are the shared
   baseline your release gate is compared against.
3. Use `expected_source` paths copied from the validator's file list.
4. Validate, evaluate your candidate, then release:

   ```bash
   uv run --project ingestion --locked python ingestion/corpus.py --docs docs/study-guides --golden evals/golden_set.yaml
   ./scripts/run-eval.sh --manual study_guides_manual
   ```

The gate uses the fraction `threshold` (0.8), not a fixed count: with 15 questions you need 12 hits.

## Reserved file: `session-13-defense-faq.md`

The initial corpus deliberately contains **no** `docs/study-guides/session-13-defense-faq.md`,
and no guide describes the capstone defense format. In the S12 stale-index drill you add this
file and release it through a tag, then show that a cited answer appears only after the release.
The file you add states the actual policy:

> Every student submits a 4-minute recorded demo. About 10 randomly selected students defend
> live; each student reviews two recordings.

That is a four-minute recording for everyone, about ten randomly selected live defenses, and
two peer reviews per student. Until that release, the live index cannot cite this policy. The
model may answer from general knowledge or say it does not know. Record what it actually does.

## Secrets

The corpus, the golden set and this README contain no credentials. Ingestion and evaluation read
the course key from `COURSE_VIRTUAL_KEY` (or the `workbench-keys` Secret). Never commit it, never
echo it, and keep it out of screenshots and evidence.
