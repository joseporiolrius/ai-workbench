"""Post-promotion smoke check: the DEPLOYED workbench answers a course question through the real
agent -> search_docs -> live alias path, from the release that was just promoted (S12, RAG-07).

    smoke_release.py --sha SHA [--namespace workbench] [--deployment workbench-pi-web-ui] [--model P/M]

It runs the pi agent that ships in the deployed pi-web-ui pod (`pi -p --mode json`, the same SDK,
models.json and extension the browser UI uses) with a golden-set question, then requires:
  * at least one successful search_docs tool call,
  * the returned passages cite docs/study-guides/... and come from corpus revision SHA,
  * a final answer.
The model is the first provider/model of the models.json the DEPLOYED pod reads (so a student's
my-values `modelsJson` override, e.g. the S9-era `provider: litellm`, is honoured); --model overrides.

Gateway rate limits: the course key is limited to a number of requests per minute, and the ingestion
that just ran used the same key. pi does not retry an HTTP 429, so an attempt that failed ONLY
because of a rate limit (429 / "rate limit" in the agent error, a tool error or stderr) is retried
after the gateway's own "Limit resets at" time (capped at 65 s) or a 20/40/60 s backoff, up to
--rate-limit-retries times. Any other failure is final on the first attempt; nothing else is retried.

Exit 0 = the intended release answers with its own corpus; 1 = anything else (reason printed).
Set WB_FAULT_INJECT=smoke to force a failure (instructor drill only).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

QUESTION = "In this DevOps course, why must the Terraform state file never be committed to Git?"
RATE_LIMIT_RE = re.compile(r"\b429\b|rate.?limit", re.I)
RESET_RE = re.compile(r"resets at:?\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", re.I)
BACKOFF_S = (20, 40, 60)
MAX_WAIT_S = 65


def deployed_model(namespace: str, deployment: str) -> str:
    """provider/model of the first entry in the pod's own models.json (pi's providers schema)."""
    run = subprocess.run(["kubectl", "-n", namespace, "exec", f"deploy/{deployment}", "--", "sh", "-c",
                          'cat "${PI_CODING_AGENT_DIR:-/app/.pi-config}/models.json"'],
                         capture_output=True, text=True, timeout=60)
    providers = json.loads(run.stdout).get("providers", {}) if run.returncode == 0 else {}
    for name, prov in providers.items():
        for m in prov.get("models", []):
            return f"{name}/{m['id']}"
    raise RuntimeError(f"no provider/model in the deployed models.json ({run.stderr.strip()[:160]})")


def evaluate(events: list[dict], stderr: str, returncode: int, sha: str) -> dict:
    """Judge one agent run. Pure: no I/O. Returns problems, the rate-limit evidence and a summary."""
    calls = [e for e in events if e.get("type") == "tool_execution_end" and e.get("toolName") == "search_docs"]
    ok_calls = [e for e in calls if not e.get("isError")]
    revisions = {e.get("result", {}).get("details", {}).get("corpusRevision") for e in ok_calls}
    sources = {h.get("source") for e in ok_calls for h in e.get("result", {}).get("details", {}).get("hits", [])}
    assistants = [m for e in events if e.get("type") == "agent_end"
                  for m in e.get("messages", []) if m.get("role") == "assistant"]
    answer = next((" ".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
                   for m in reversed(assistants)), "")
    tool_errors = [json.dumps(e.get("result", {}))[:400] for e in calls if e.get("isError")]
    agent_errors = [str(m.get("errorMessage")) for m in assistants if m.get("errorMessage")]
    evidence = " | ".join(agent_errors + tool_errors + ([stderr[-400:]] if stderr else []))
    problems = []
    if returncode != 0 and not events:
        problems.append(f"pi exited {returncode}: {stderr.strip()[:200]}")
    if not ok_calls:
        problems.append(f"no successful search_docs call ({len(calls)} call(s), errors: "
                        f"{[e.get('result', {}).get('content', [{}])[0].get('text', '')[:120] for e in calls]})")
    if ok_calls and revisions != {sha}:
        problems.append(f"passages came from corpus revision(s) {sorted(map(str, revisions))}, not {sha}")
    if ok_calls and not any(str(s).startswith("docs/study-guides/") for s in sources):
        problems.append("no docs/study-guides citation in the returned passages")
    if not answer.strip():
        problems.append("no final answer" + (f" (agent error: {agent_errors[-1][:160]})" if agent_errors else ""))
    rate_limited = bool(problems) and bool(RATE_LIMIT_RE.search(evidence))
    return {"problems": problems, "rate_limited": rate_limited, "evidence": evidence,
            "calls": len(ok_calls), "sources": sorted(map(str, sources)), "answer": answer.strip()}


def rate_limit_wait(evidence: str, attempt: int, now: datetime | None = None) -> int:
    """Seconds to wait before the next attempt: the gateway's reset time if stated, else backoff."""
    match = RESET_RE.search(evidence)
    if match:
        reset = datetime.fromisoformat(match.group(1).replace(" ", "T")).replace(tzinfo=timezone.utc)
        secs = int((reset - (now or datetime.now(timezone.utc))).total_seconds()) + 2
        if secs > 0:
            return min(secs, MAX_WAIT_S)
    return BACKOFF_S[min(attempt - 1, len(BACKOFF_S) - 1)]


def run_agent(namespace: str, deployment: str, model: str, timeout: int) -> tuple[list[dict], str, int]:
    cmd = ["kubectl", "-n", namespace, "exec", f"deploy/{deployment}", "--", "sh", "-c",
           "cd /tmp && /app/node_modules/.bin/pi -p --no-session --mode json --model \"$1\" \"$0\"", QUESTION, model]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    return events, run.stderr, run.returncode


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--namespace", default=os.environ.get("WB_NAMESPACE", "workbench"))
    p.add_argument("--deployment", default="workbench-pi-web-ui")
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--model", help="provider/model (default: first entry of the deployed models.json)")
    p.add_argument("--rate-limit-retries", type=int, default=int(os.environ.get("SMOKE_RATE_LIMIT_RETRIES", "3")),
                   help="extra attempts after an HTTP 429 from the gateway (default 3)")
    args = p.parse_args()
    if os.environ.get("WB_FAULT_INJECT") == "smoke":
        print("[smoke] FAILED: injected fault (WB_FAULT_INJECT=smoke)", file=sys.stderr)
        return 1
    try:
        model = args.model or deployed_model(args.namespace, args.deployment)
    except (RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"[smoke] FAILED: cannot read the deployed models.json: {exc}", file=sys.stderr)
        return 1
    attempts = 1 + max(args.rate_limit_retries, 0)
    for attempt in range(1, attempts + 1):
        try:
            events, stderr, rc = run_agent(args.namespace, args.deployment, model, args.timeout)
        except subprocess.TimeoutExpired:
            print(f"[smoke] FAILED: no answer within {args.timeout}s", file=sys.stderr)
            return 1
        result = evaluate(events, stderr, rc, args.sha)
        if not result["problems"]:
            print(f"[smoke] OK: model {model}, {result['calls']} search_docs call(s), corpus revision {args.sha[:12]}, "
                  f"sources {result['sources'][:3]}, answer {result['answer'][:100]!r}"
                  + (f" (after {attempt - 1} rate-limit retr{'y' if attempt == 2 else 'ies'})" if attempt > 1 else ""))
            return 0
        if result["rate_limited"] and attempt < attempts:
            wait = rate_limit_wait(result["evidence"], attempt)
            print(f"[smoke] gateway rate limit (HTTP 429) on attempt {attempt}/{attempts}; "
                  f"waiting {wait}s for the key's request window to reset", file=sys.stderr)
            time.sleep(wait)
            continue
        why = "\n  ".join(result["problems"])
        tail = " (still rate-limited after all retries)" if result["rate_limited"] else ""
        print(f"[smoke] FAILED{tail}:\n  {why}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
