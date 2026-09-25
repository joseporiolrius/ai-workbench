---
title: "Session 01 — Kickoff: Why Industrialize Software (and AI)"
session: 01
source: "oriolrius/esade-devops:backlog/docs/doc-3 - Session-01-Kickoff.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 01 — Kickoff: Why Industrialize Software (and AI)

Session 01 is the course's zero point: no accounts, no tools, no assumptions beyond a laptop and a browser. It gets every student from nothing to a working, auditable Git loop — private repository, real commit, green automated check — while setting the honest terms under which AI assistance is used and verified all semester. The end state: a private `hello-world` repository with the professor as collaborator, a signed AI-use contract, and a first journal entry.

## Why industrialize: the boardroom thesis

The course's one-line thesis: coding is the automation of thought, DevOps is the automation of coding's delivery, and MLOps extends that automation to systems that learn. Industrialized companies ship faster and break less at the same time — explicitly not a tradeoff. DORA research anchors this: elite performers deploy on demand, multiple times per day, with change-failure rates around 5% and recovery under an hour; low performers deploy between once a month and once every six months, fail more than 40% of the time, and take weeks to recover, using the same tools. The AI angle: a graduate who can only prompt an AI product pays the vendor's price, while one who can operate an equivalent system (deploy, secure, monitor its cost) can compare a SaaS subscription against self-run infrastructure with evidence and negotiate from strength. The discussion question asks what students would need to know — not believe — to make a buy-vs-build call.

## The five things to know cold

Session 1's quiz and exam contract rests on five ideas; the Session 2 warm-up quiz draws only from this list. DevOps unifies development and operations so shipping fast and staying stable reinforce each other through automation, resolving the dev-vs-ops conflict rather than picking a side. A pipeline is an automated, repeatable sequence of steps that takes a change from commit to a verified, released, or running state without manual intervention — humans design it, machines run it identically every time. MLOps extends DevOps because an ML system versions three artifact types — code, data, and model — while plain software versions only code. A commit is an immutable snapshot identified by a unique SHA, carrying author, timestamp, and message, making any past state addressable. A conventional commit message has the form `type(scope): description` (e.g. `feat: add health endpoint`, `fix: correct port number`), where the machine-readable type later drives changelogs and version bumps.

## The lab: first commit, first green pipeline

The lab is entirely browser-based — no local installs, no terminal. The course template is `github.com/oriolrius/hello-world`, a public repository marked as a Template repository. Students use "Use this template → Create a new repository" rather than the Fork button, because a GitHub fork of a public repo cannot be made private, while template instantiation produces an independent private copy — the first operations lesson of the course. Students set visibility to Private and add the professor as collaborator (all course repos are private with the professor as collaborator). The repo-creation push triggers the pre-provided workflow `.github/workflows/hello.yml`, which students read (not write) in the Actions tab: checkout, install `uv`, run `uv run python hello.py`.

In Block B, students open `github.dev` (press `.` on the repo page) for browser VS Code with no install, edit `ABOUT.md`, and make their first conventional commit (`docs: add student profile`) directly to `main`. They then run an AI-assisted micro-task: paste `.github/workflows/hello.yml` into any AI assistant, ask it to explain the workflow, and verify every claim against the Actions log — typical failures include describing steps not in the file or inventing triggers such as pull requests. This seeds every later journal entry, which closes the session along with a screenshot uploaded to `evidence/s01-actions-green.png`.

## The AI-use contract

Session 1 introduces the honest deal governing AI use all semester: AI-open labs paired with a mandatory journal, closed-book eCampus micro-quizzes drawn only from published know-cold lists, rolling oral spot-defenses on the student's own artifact, and fault-injection practicals in the student's own running system. Stated verbatim: "AI writes code fast; your job — and your grade — is knowing whether it's right." Every journal entry records four things: what was asked of the AI, what it got wrong (or how correctness was verified), what was changed or concluded, and how it was verified. This is acknowledged in `JOURNAL.md`'s header — spot-checks probe whether a student can defend a journal claim against their own Actions log.

## Common failure modes, spot-checks, and the demo-the-target pattern

The classic AI mistake this week: an assistant told to "make a private copy from the template" claims a public fork can be flipped to private in Settings, or gives a local-terminal recipe (`git clone` + `gh repo create --private`) on a browser-only lab day — instructors watch for terminal commands pasted into nothing. A second classic mistake is AI-suggested commit messages written as long, capitalized prose instead of conventional format. Diagnosis is the skill trained all semester: read the actual log or UI, not the assistant's confident description of it. Instructors cold-call two or three students per session to defend their own artifact; Session 1's questions include what exactly triggered the Actions run, which part of the commit message is the type, and why the repo is not a fork. The instructor also demos the finished Private AI Workbench (pi-web-ui, Qdrant, Grafana, talking to the professor-operated course gateway) as a "demo-the-target": every element is labeled with the session number where students build it themselves.

## What is deferred, and the deliverable

The course cuts day-one overload from the previous edition (61 slides down to about 25): feature stores, the SageMaker platform tour, MLOps maturity levels, and the EU AI Act are named as deferred — model tracking returns in Session 11 with MLflow, RAG/LLM operations in Session 12. The deliverable due before Session 2 is the repo URL submitted via eCampus, graded on: private repo with professor collaborator, at least three conventional commits, a journal entry naming a verified AI claim, and a green Actions run.
