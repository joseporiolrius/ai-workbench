"""Unit tests for the release smoke's judgement and gateway rate-limit handling (S12, starter v1.0.1)."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "smoke_release", Path(__file__).resolve().parents[2] / "scripts" / "smoke_release.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)

SHA = "a" * 40
LIMIT = ("litellm.RateLimitError: RateLimitError: OpenAIException - Rate limit exceeded for api_key: ***. "
         "Limit type: requests. Current limit: 60, Remaining: 0. Limit resets at: 2026-09-25 16:09:58 UTC.")


def tool(ok=True, source="docs/study-guides/session-06-terraform-iac.md", rev=SHA, text=""):
    return {"type": "tool_execution_end", "toolName": "search_docs", "isError": not ok,
            "result": {"details": {"corpusRevision": rev, "hits": [{"source": source}]},
                       "content": [{"type": "text", "text": text}]}}


def end(text="The state file maps code to resources.", error=None):
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}] if text else []}
    if error:
        msg["errorMessage"] = error
    return {"type": "agent_end", "messages": [msg]}


def test_good_run_passes():
    r = smoke.evaluate([tool(), end()], "", 0, SHA)
    assert r["problems"] == [] and not r["rate_limited"]


def test_chat_429_is_rate_limited():
    r = smoke.evaluate([end(text="", error=LIMIT)], "", 0, SHA)
    assert r["problems"] and r["rate_limited"]


def test_search_docs_429_is_rate_limited():
    r = smoke.evaluate([tool(ok=False, text="search_docs: gateway returned HTTP 429: rate limited"),
                        end(text="I could not search.")], "", 0, SHA)
    assert r["rate_limited"]


def test_wrong_revision_is_final_not_rate_limited():
    r = smoke.evaluate([tool(rev="b" * 40), end()], "", 0, SHA)
    assert r["problems"] and not r["rate_limited"]


def test_other_agent_error_is_not_retried():
    r = smoke.evaluate([end(text="", error="Connection refused")], "", 0, SHA)
    assert r["problems"] and not r["rate_limited"]


def test_wait_uses_gateway_reset_time():
    now = datetime(2026, 9, 25, 16, 9, 30, tzinfo=timezone.utc)
    assert smoke.rate_limit_wait(LIMIT, 1, now) == 30          # 28 s to reset + 2 s margin


def test_wait_is_capped_and_falls_back_to_backoff():
    far = datetime(2026, 9, 25, 16, 0, 0, tzinfo=timezone.utc)
    assert smoke.rate_limit_wait(LIMIT, 1, far) == smoke.MAX_WAIT_S
    past = datetime(2026, 9, 25, 17, 0, 0, tzinfo=timezone.utc)
    assert smoke.rate_limit_wait(LIMIT, 2, past) == smoke.BACKOFF_S[1]
    assert smoke.rate_limit_wait("HTTP 429", 9) == smoke.BACKOFF_S[-1]


def test_wait_has_a_floor_when_the_reset_is_imminent():
    now = datetime(2026, 9, 25, 16, 9, 57, tzinfo=timezone.utc)
    assert smoke.rate_limit_wait(LIMIT, 1, now) == smoke.MIN_WAIT_S
