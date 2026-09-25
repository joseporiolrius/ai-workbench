"""Atomic promotion / restore of the live Qdrant alias `study_guides` (S12, RAG-06).

Called by scripts/promote-corpus.sh under the production lock, with QDRANT_URL pointing at its own
forward. Never deletes or writes a physical collection.

    corpus_alias.py promote --candidate C --state DIR [--receipt-sha256 H]
    corpus_alias.py restore --to C --state DIR          # C must have been promoted before
    corpus_alias.py remove  --expect C --state DIR      # only for a failed FIRST release (RAG-07)

A promotion is ONE Qdrant alias request (delete_alias + create_alias), which Qdrant applies
atomically: readers see the old target or the new one, never a missing alias. Afterwards the alias
and the candidate's point count are verified; any failure restores the previous target (or removes
the alias created by a failed first promotion) and exits 1. Records: <state>/promotion.json and
<state root>/promotions.log (JSON lines). Exit: 0 ok, 1 failed (prior state kept or restored).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
import rag  # noqa: E402

ALIAS = "study_guides"


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def switch(q: rag.Qdrant, target: str | None, current: str | None) -> None:
    """Point ALIAS at target (None = remove it) in a single atomic request."""
    actions = [{"delete_alias": {"alias_name": ALIAS}}] if current else []
    if target:
        actions.append({"create_alias": {"collection_name": target, "alias_name": ALIAS}})
    if actions:
        q.call("POST", "/collections/aliases", json={"actions": actions})


def check(q: rag.Qdrant, expected: str) -> None:
    live = q.aliases().get(ALIAS)
    if live != expected:
        raise rag.RagError(f"alias {ALIAS} -> {live!r} after the switch, expected {expected!r}")
    rag.verify_complete(q, ALIAS)          # the alias resolves to a complete candidate
    if os.environ.get("WB_FAULT_INJECT") == "alias-verify":   # test-only drill hook (documented)
        raise rag.RagError("injected fault: post-switch verification failed (WB_FAULT_INJECT=alias-verify)")


def record(state: Path, entry: dict) -> None:
    state.mkdir(parents=True, exist_ok=True)
    (state / "promotion.json").write_text(json.dumps(entry, indent=2) + "\n")
    with open(state.parent / "promotions.log", "a") as log:
        log.write(json.dumps(entry) + "\n")


def promoted_before(state: Path, collection: str) -> bool:
    log = state.parent / "promotions.log"
    return log.is_file() and any(json.loads(line).get("new") == collection and json.loads(line).get("status") == "promoted"
                                 for line in log.read_text().splitlines() if line.strip())


def transition(q: rag.Qdrant, state: Path, action: str, target: str | None, extra: dict) -> int:
    previous = q.aliases().get(ALIAS)
    entry = {"action": action, "previous": previous, "new": target, "time_utc": now(), **extra}
    try:
        if target:
            rag.verify_complete(q, target)          # never point the alias at a missing/partial collection
        switch(q, target, previous)
        if target:
            check(q, target)
        entry["status"] = "promoted" if action == "promote" else action + "d"
        record(state, entry)
        print(f"[alias] {ALIAS}: {previous or '(none)'} -> {target or '(none)'}  ({entry['status']}); "
              f"previous collection kept: {previous or 'n/a'}")
        return 0
    except rag.RagError as exc:
        entry["error"] = str(exc)
        try:
            live = q.aliases().get(ALIAS)
            if live != previous:
                switch(q, previous, live)            # restore, or remove an alias a failed first promotion created
            entry["status"] = "failed-restored"
            entry["restored_to"] = previous
        except rag.RagError as restore_exc:
            entry["status"] = "failed-UNRESTORED"
            entry["restore_error"] = str(restore_exc)
        record(state, entry)
        print(f"[alias] FAILED: {exc}", file=sys.stderr)
        if entry["status"] == "failed-restored":
            print(f"[alias] live alias restored to {previous or '(no alias: first release)'}", file=sys.stderr)
        else:
            print(f"[alias] COULD NOT RESTORE ({entry['restore_error']}). Production may be inconsistent: run "
                  f"scripts/recover-production.sh, then scripts/promote-corpus.sh --restore {previous}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("action", choices=["promote", "restore", "remove"])
    p.add_argument("--candidate"); p.add_argument("--to"); p.add_argument("--expect")
    p.add_argument("--state", required=True)
    p.add_argument("--receipt-sha256", default=None)
    args = p.parse_args(argv)
    q, state = rag.Qdrant(), Path(args.state)
    try:
        if args.action == "promote":
            return transition(q, state, "promote", args.candidate, {"receipt_sha256": args.receipt_sha256})
        if args.action == "restore":
            undoing = (state / "promotion.json").is_file() and \
                json.loads((state / "promotion.json").read_text()).get("previous") == args.to
            if not (promoted_before(state, args.to) or undoing):
                print(f"[alias] REFUSED: {args.to} was never promoted (promotions.log); restore only to a "
                      f"previously live, evaluated collection", file=sys.stderr)
                return 1
            return transition(q, state, "restore", args.to, {})
        live = q.aliases().get(ALIAS)                # remove: only undoes our own failed first release
        if live != args.expect:
            print(f"[alias] REFUSED: alias points at {live!r}, not {args.expect!r}", file=sys.stderr)
            return 1
        return transition(q, state, "remove", None, {})
    except rag.RagError as exc:
        print(f"[alias] FAILED before any change: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
