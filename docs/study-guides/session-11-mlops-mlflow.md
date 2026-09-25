---
title: "Session 11 — MLOps: Models Are Artifacts Too"
session: 11
source: "oriolrius/esade-devops:backlog/docs/doc-13 - Session-11-MLOps-MLflow.md"
source_revision: 4a391ec3847b48d414a2ff3b35a9092eb319984d
---

# Session 11 — MLOps: Models Are Artifacts Too

Session 11 steps off the k3s cluster entirely: MLflow's tracking server and model registry run as a `uv` process on the student's own VM, off-cluster on purpose, to train and compare a predictive-maintenance "overheat" model, register the best version, and write a quality-gate script that passes a good model and rejects a bad one by exit code — the exact pattern Session 12 reuses for RAG retrieval quality.

## Why models rot without tracking

The boardroom frames the stakes: 87% of ML projects never reach production because a notebook result can't be reproduced, validated, or operated, and Zillow Offers' 2021 house-pricing model kept buying as the market turned, producing a roughly $500M inventory write-down and a shut-down business unit — the model wasn't wrong on day one, the world changed and nothing measured the decay (drift as a line item on an income statement). The course's claim: a model is not an asset until it is a tracked, versioned, gated, monitored artifact — everything else is a demo. A reproducible ML run requires four things: code version (git commit), data version, hyperparameters, and metrics; if any one is untracked, nobody can say which model is in production or how it got there.

## Tracking vs registry, and the quality gate

Experiment tracking records every run — params, metrics, artifacts — during experimentation; the model registry holds only the selected few as numbered versions with a promotion lifecycle. They exist because "what did we try?" and "what do we ship?" are different questions. A quality gate is an automated assertion on a metric threshold sitting between training and promotion, communicating purely through its process exit code: 0 means pass, non-zero means the pipeline stops — deploys are blocked by the gate, not debated in a meeting. Data drift (the input distribution shifts, e.g. a sensor recalibrated) and concept drift (the input→label relationship shifts, e.g. a new machine type overheats at a different temperature) are why models need the same monitoring discipline as services, without any code change.

## The overheat-model repo and lab structure

The course repo `github.com/oriolrius/overheat-model` (adapted from the archived `oriolrius/sagemaker-unified-studio-demo` notebook sequence into plain `uv` scripts) simulates predictive maintenance: 5 machines, 216K synthetic temperature readings, an engineered `temp_diff` feature, a binary `overheat` label (core temperature > 80°C), and LogisticRegression. Students work in a private copy from the template with the professor as collaborator. Layout: `src/generate_data.py` (deterministic, seeded), `src/train.py` (CLI flags `--c`, `--features`, logs to MLflow), `src/register.py` (registers a run as a model version), `src/quality_gate.py` (asserts `accuracy >= threshold`, exits 0/1), plus `evidence/` and `JOURNAL.md`. `pyproject.toml` pins `mlflow`, `scikit-learn`, `pandas`, `pyarrow` — this course always uses `uv sync` / `uv run`, never raw `pip install`.

## Running the server and the hyperparameter sweep

The MLflow server binds to loopback only — `uv run mlflow server --host 127.0.0.1 --port 5000 --backend-store-uri sqlite:///mlflow.db --artifacts-destination ./mlartifacts` — because the VM is public and MLflow ships with no authentication; the same "make it private" lesson as Session 09's ingress milestone. The UI is reached from the laptop via `ssh -L 5000:127.0.0.1:5000`. `MLFLOW_TRACKING_URI=http://127.0.0.1:5000` must be exported in the training shell, or runs silently land in a local `./mlruns` directory instead of the server — the classic AI-generated mistake, symptom: "training succeeds but the UI stays empty." A baseline run (`--run-name baseline-c1`) plus a sweep over regularization strength `C` (`0.001, 0.01, 0.1, 1.0, 10, 100`) produces at least 6 tracked runs, each carrying params (`c`, `features`, seed), metrics (`accuracy`, `f1`), the model artifact, and the git commit — the reproducibility receipt.

## Comparing, registering, and gating

In the MLflow UI, selecting all runs and choosing Compare shows a parallel-coordinates view of `c` against accuracy. The best run is registered as model `overheat-classifier` (via the UI's "Register model" button or `src/register.py --run-id <ID> --name overheat-classifier`), producing version 1. `quality_gate.py` is deliberately tiny: it fetches the run behind a model version, reads `run.data.metrics["accuracy"]`, and either prints `PASSED` and exits 0, or prints `REJECTED: accuracy ... < ...` and exits 1. Running it against version 1 with `--min-accuracy 0.85` exits 0. Training a deliberately bad model — dropping the engineered `temp_diff` feature (`--features temp_a,temp_b`) — and registering it as version 2 makes the same gate print `REJECTED` and exit 1, because the feature engineering *was* the value. That `exit 1` is exactly what a GitHub Actions step reads, and Session 12 reuses the identical three-line gate pattern against a RAG hit@k score instead of accuracy.

## Evidence, checkpoints, and things to know cold

Checkpoint A is 6 runs visible in the UI with differing `c` and accuracy; the expected end state is ≥7 tracked runs, `overheat-classifier` v1 (passing) and v2 (rejected), plus three screenshots (`compare-runs.png`, `registered-v1.png`, `gate-rejected.png`) committed with `JOURNAL.md` — `mlflow.db`, `mlartifacts/`, and `data/` stay gitignored, only evidence and journal go to git. "A pipeline is CI/CD for ML" is the same shape as any pipeline (trigger, steps, quality gate, versioned artifact, deploy), except the artifacts are data and models and the "tests" are metric thresholds. Managed platforms (SageMaker, Vertex AI, Azure ML, Databricks) get exactly one comparison slide: they bundle the same four boxes — tracking, registry, pipelines, monitoring — as a paid service, and SageMaker's own tracking today *is* managed MLflow. Deploying MLflow to Kubernetes, serving the model as an endpoint, feature stores, AutoML, distributed training, and GPUs are explicitly out of scope this session.

## Common failure modes to diagnose

"Invisible runs" (unset `MLFLOW_TRACKING_URI`, runs go to `./mlruns` instead of the server) is diagnosed by checking where the client thinks the tracking server is. "The gate that lies" (a professor-style fault injection reading the wrong metric key, or `--min-accuracy` lowered to 0.5) lets a plainly bad model pass — diagnosed by demonstrating the pass, inspecting the gate script, fixing the threshold or key, and re-demonstrating rejection.
