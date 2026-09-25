---
title: "Session 07 — Midterm Exam"
session: 07
source: "oriolrius/esade-devops:backlog/docs/doc-9 - Session-07-Midterm.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 07 — Midterm Exam

Session 07 is the midterm: a 180-minute exam proving the student can explain (closed-book) and
repair, under live fault conditions with AI assistance allowed, the automated delivery system
built across Sessions 1–6. It counts for 20% of the course grade. The end state is a healthy
stack, a merged `exam/midterm` pull request with green CI, and a graded journal — S8 must start
from a known-good environment, so a final health verification is mandatory before the exam ends.

## Structure and timing

The exam runs 180 minutes in two graded parts plus setup and wrap-up. Part A — Theory (~60
minutes) is closed-book: no AI, no notes, no phones, no second window, delivered through the Test
Wizard tool; roughly 20 items of single-answer MCQ and 1–2-sentence short answers, about 3 minutes
per item. After a short transition (per-student fault patch issued; instructor-side VM faults
already armed), Part B — Practical (~100 minutes) is AI-open: any assistant, any docs, but no
human-to-human help. Work happens on branch `exam/midterm`, and the fix PR with green CI is itself
graded evidence. The final 10 minutes are mandatory end-state verification, final journal commit,
and submission.

## Scope: only the published know-cold lists

Part A theory questions draw only from the "5 things to know cold" lists published in the
Session 1–6 study material — nothing outside those lists is examinable. Coverage spans: Session 1
(why industrialize; Git basics; conventional commits), Session 2 (Linux/SSH/processes/ports/YAML;
why manual ops fail), Session 3 (CI, branch protection, PR flow, workflow anatomy), Session 4
(images vs containers, Dockerfile layers, Compose), Session 5 (CD, semver tags, GHCR, pinning, the
deploy job), and Session 6 (IaC, declarative state, idempotency, security groups, cloud-init). Best
preparation: a cold re-read of each know-cold list plus practicing the exact commands and
diagnostic reasoning behind each item — nothing outside that bounded scope is tested, but fluency
inside it is expected.

## Part B: fault injection in your own project

The practical injects two faults per student, drawn from different areas of the S1–S6 stack (for
example: the CI workflow, the release/CD chain, Dockerfile or Compose configuration, server-side
process/port state, or Terraform/security-group configuration). Faults are per-student variants,
so no two neighbors see the identical pair, and each fault is deterministic and diagnosable using
only tools already taught in Sessions 1–6. Some faults arrive as a git patch applied to a new
`exam/midterm` branch at the start of Part B; others are injected live on the student's VM by the
instructor during Part A. Every task variant shares one closing verification: CI green on the
`exam/midterm` PR, `docker compose ps` healthy, hello-world and the workbench reachable from the
laptop, `terraform plan` reporting no changes, and a final journal entry committed.

## Diagnostic discipline: read logs before guessing

Across all fault types, the graded skill is the diagnostic path, not luck: read the actual error
output (Actions run logs, `docker compose logs`, `ss -ltnp`, `terraform plan` diffs,
`/var/log/cloud-init-output.log`) before changing anything, change one thing at a time, and verify
with a command or curl output — not just "it looks fixed." Some symptoms look identical locally
but have different root causes (a process bound to the wrong interface versus a security-group
rule blocking external access); the exam expects the correct tool for each layer, not guesswork.

## The journal is graded evidence, not paperwork

`JOURNAL.md` gains a `## Midterm` section with at least one commit per fault plus a final commit
(minimum three; timestamps are evidence). Each fault entry needs five things: the symptom
observed verbatim, the hypothesis and why, what AI was asked and what it got wrong or was
rejected, the fix (referencing the commit), and the verification proving it worked. An empty,
retro-fitted, or fabricated journal caps the Troubleshooting component at zero and triggers an
oral check that can also discount the Implementation score.

## Grading rubric

Per the syllabus, the midterm score (0–10, weighing 20% of the course grade) splits into
Implementation 60 points (each fault fixed and verified worth 25, plus 10 for complete closing
verification, committed evidence, and a green PR), Conceptual accuracy 25 points (Test Wizard
Part A score scaled to 25), and Troubleshooting & reasoning 15 points (journal quality and
honesty worth 10, sound diagnosis worth 5). Partial credit exists per fault: full credit requires
the root cause fixed and verified; half credit applies when the symptom is patched without
addressing the root cause (the canonical half-credit case is a console-clicked security-group fix
that a subsequent `terraform plan` would revert — drift, the ClickOps failure mode from Session 6);
quarter credit applies when a fault is correctly diagnosed in the journal but never repaired.

## Anti-cheating design and logistics

The exam design defeats cheating vectors by construction rather than policing: the practical
happens inside each student's own repo with a semester of their own git history, on a VM only they
and the instructor can reach, so AI can propose fixes but diagnosis requires reading a live system
the student must understand — the graded skill, with AI use journaled rather than banned.
Closed-book Test Wizard with phones away and no second window defeats outsourced memorization;
per-student fault variants defeat answer-sharing; commit timestamps, the patch-apply commit,
journal cadence, and Actions run history give a forensic trail that flags anomalies (a
suspiciously fast fix with an empty journal), triggering an oral "explain this line" check.

## Retakes and the forward-looking recovery path

There is no separate midterm retake: the original score carries into any retake round unchanged,
so recovery from a weak midterm is forward-looking rather than a do-over — the post-exam feedback
loop, the project component (30% of the grade), and the comprehensive final exam (40%, re-testing
the same S1–S6 foundations). A student who misses the exam with justified cause sits an equivalent
make-up: same structure, a different fault pair from the same menu, theory from the same
know-cold lists. Fault classes recur later in Kubernetes-flavored form (a Compose port-mapping
fault reappears as a Service selector fault in Session 9), so gaps exposed here are worth closing
before later sessions build on them.
