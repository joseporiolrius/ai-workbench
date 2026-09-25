"""Post-promotion smoke check: the DEPLOYED workbench answers a course question through the real
agent -> search_docs -> live alias path, from the release that was just promoted (S12, RAG-07).

    smoke_release.py --sha SHA [--namespace workbench] [--deployment workbench-pi-web-ui]

It runs the pi agent that ships in the deployed pi-web-ui pod (`pi -p --mode json`, the same SDK,
models.json and extension the browser UI uses) with a golden-set question, then requires:
  * at least one successful search_docs tool call,
  * the returned passages cite docs/study-guides/... and come from corpus revision SHA,
  * a final answer.
Exit 0 = the intended release answers with its own corpus; 1 = anything else (reason printed).
Set WB_FAULT_INJECT=smoke to force a failure (instructor drill only).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

QUESTION = "In this DevOps course, why must the Terraform state file never be committed to Git?"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sha", required=True)
    p.add_argument("--namespace", default=os.environ.get("WB_NAMESPACE", "workbench"))
    p.add_argument("--deployment", default="workbench-pi-web-ui")
    p.add_argument("--timeout", type=int, default=240)
    args = p.parse_args()
    if os.environ.get("WB_FAULT_INJECT") == "smoke":
        print("[smoke] FAILED: injected fault (WB_FAULT_INJECT=smoke)", file=sys.stderr)
        return 1
    cmd = ["kubectl", "-n", args.namespace, "exec", f"deploy/{args.deployment}", "--", "sh", "-c",
           "cd /tmp && /app/node_modules/.bin/pi -p --no-session --mode json --model course/course-chat \"$0\"", QUESTION]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f"[smoke] FAILED: no answer within {args.timeout}s", file=sys.stderr)
        return 1
    events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith("{")]
    calls = [e for e in events if e.get("type") == "tool_execution_end" and e.get("toolName") == "search_docs"]
    ok_calls = [e for e in calls if not e.get("isError")]
    revisions = {e.get("result", {}).get("details", {}).get("corpusRevision") for e in ok_calls}
    sources = {h.get("source") for e in ok_calls for h in e.get("result", {}).get("details", {}).get("hits", [])}
    answer = next((" ".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
                   for e in events if e.get("type") == "agent_end"
                   for m in reversed(e.get("messages", [])) if m.get("role") == "assistant"), "")
    problems = []
    if run.returncode != 0 and not events:
        problems.append(f"pi exited {run.returncode}: {run.stderr.strip()[:200]}")
    if not ok_calls:
        problems.append(f"no successful search_docs call ({len(calls)} call(s), errors: "
                        f"{[e.get('result', {}).get('content', [{}])[0].get('text', '')[:120] for e in calls]})")
    if ok_calls and revisions != {args.sha}:
        problems.append(f"passages came from corpus revision(s) {sorted(map(str, revisions))}, not {args.sha}")
    if ok_calls and not any(str(s).startswith("docs/study-guides/") for s in sources):
        problems.append("no docs/study-guides citation in the returned passages")
    if not answer.strip():
        problems.append("no final answer")
    if problems:
        print("[smoke] FAILED:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"[smoke] OK: {len(ok_calls)} search_docs call(s), corpus revision {args.sha[:12]}, "
          f"sources {sorted(sources)[:3]}, answer {answer.strip()[:100]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
