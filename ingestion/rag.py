"""Shared S12 retrieval helpers: settings, chunking, gateway embeddings, Qdrant REST.

ingest.py, search.py and the evaluator import this module. Everything here is plain
HTTP (httpx) against two services:

- the course gateway (OpenAI-compatible ``POST /embeddings``), authenticated with
  ``COURSE_VIRTUAL_KEY``. The key is sent only in the Authorization header. It is
  never printed, logged or stored in a payload.
- Qdrant's REST API at ``QDRANT_URL`` (default ``http://127.0.0.1:6333``, i.e. a
  ``kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333``).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import yaml

from corpus import CorpusError, Document

SETTINGS_KEYS = {"embedding_model", "collection_prefix", "chunk_size", "chunk_overlap", "top_k"}
PROTECTED = {"monitoring_demo"}  # S10 fixture: ingestion never writes it
NAME = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
EMBED_PARALLEL = 4
RETRIES = 3
RATE_LIMIT_RETRIES = 8


_qualification_requests = 0
_qualification_next_request = 0.0


class RagError(CorpusError):
    """A usage, gateway or Qdrant failure. Exit nonzero, print the message."""


# ------------------------------------------------------------------ settings + contract

def load_settings(path: str | Path = "rag-settings.yaml") -> dict:
    try:
        settings = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RagError(f"settings not found: {path} (run from the ai-workbench root)") from exc
    except yaml.YAMLError as exc:
        raise RagError(f"settings are not valid YAML: {exc}") from exc
    if not isinstance(settings, dict):
        raise RagError(f"{path} must be a mapping")
    errors = []
    if set(settings) != SETTINGS_KEYS:
        missing, extra = SETTINGS_KEYS - set(settings), set(settings) - SETTINGS_KEYS
        errors += [f"missing keys {sorted(missing)}"] if missing else []
        errors += [f"unknown keys {sorted(extra)}"] if extra else []
    model, prefix = settings.get("embedding_model"), settings.get("collection_prefix")
    if not isinstance(model, str) or not model.strip():
        errors.append("embedding_model must be a non-empty alias name")
    if not isinstance(prefix, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", prefix or ""):
        errors.append("collection_prefix must match [a-z][a-z0-9_]*")
    size, overlap, top_k = (settings.get(k) for k in ("chunk_size", "chunk_overlap", "top_k"))
    if not _int(size) or not 200 <= size <= 4000:
        errors.append(f"chunk_size must be an integer in 200..4000, got {size!r}")
    elif not _int(overlap) or not 0 <= overlap <= size // 2:
        errors.append(f"chunk_overlap must be an integer in 0..chunk_size/2, got {overlap!r}")
    if not _int(top_k) or not 1 <= top_k <= 50:
        errors.append(f"top_k must be an integer in 1..50, got {top_k!r}")
    if errors:
        raise RagError(f"invalid {path}: " + "; ".join(errors))
    return settings


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def contract(path: str | Path = "course-artifacts.yaml") -> dict:
    """course-artifacts.yaml › retrieval: gateway URL, fixed query alias, dimension."""
    try:
        retrieval = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["retrieval"]
        return {
            "gateway": os.environ.get("COURSE_GATEWAY_URL", retrieval["gateway_base_url"]).rstrip("/"),
            "query_model": retrieval["evaluator_query_alias"],
            "dimension": int(retrieval["embedding_dimension"]),
        }
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise RagError(f"cannot read the retrieval contract from {path}: {exc!r}") from exc


# ------------------------------------------------------------------ chunking

@dataclass(frozen=True)
class Chunk:
    source: str      # citation path, e.g. docs/study-guides/session-06-terraform-iac.md
    title: str
    section: str
    index: int       # position within its document
    text: str        # what is embedded and returned: "<title> — <section>\n\n<body>"


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            meta = yaml.safe_load(text[4:end]) or {}
            return (meta if isinstance(meta, dict) else {}), text[end + 5:]
    return {}, text


def chunk_document(doc: Document, size: int, overlap: int) -> list[Chunk]:
    """Split by ``#``/``##`` headings, then pack paragraphs (or sentences of long
    paragraphs) into chunks of at most ``size`` characters. Consecutive chunks of the
    same section repeat up to ``overlap`` trailing characters."""
    meta, body = split_front_matter(doc.text)
    title = str(meta.get("title") or Path(doc.path).stem)
    sections, heading, lines = [], title, []
    for line in body.splitlines():
        if re.match(r"^#{1,2} ", line):
            sections.append((heading, "\n".join(lines)))
            heading, lines = line.lstrip("#").strip(), []
        else:
            lines.append(line)
    sections.append((heading, "\n".join(lines)))

    chunks = []
    for section, text in sections:
        prefix = title if section == title else f"{title} — {section}"
        budget = max(size - len(prefix) - 2, 100)
        for body_text in _pack(text, budget, overlap):
            chunks.append(Chunk(doc.path, title, section, len(chunks), f"{prefix}\n\n{body_text}"))
    return chunks


def _pack(text: str, budget: int, overlap: int) -> list[str]:
    units = []
    for para in (p.strip() for p in re.split(r"\n\s*\n", text)):
        if not para:
            continue
        if len(para) <= budget:
            units.append(para)
        else:
            units += [s for s in re.split(r"(?<=[.!?;:])\s+", para) if s]
    out, current = [], ""
    for unit in units:
        while len(unit) > budget:           # a single overlong "sentence": hard split
            if current:
                out.append(current)
                current = ""
            out.append(unit[:budget])
            unit = unit[budget:]
        candidate = f"{current} {unit}".strip() if current else unit
        if len(candidate) <= budget:
            current = candidate
            continue
        out.append(current)
        tail = current[-overlap:] if overlap else ""
        tail = tail[tail.find(" ") + 1:] if " " in tail else tail
        current = f"{tail} {unit}".strip() if tail and len(tail) + len(unit) < budget else unit
    if current:
        out.append(current)
    return out


# ------------------------------------------------------------------ gateway embeddings

def course_key() -> str:
    key = os.environ.get("COURSE_VIRTUAL_KEY", "").strip()
    if not key:
        raise RagError("COURSE_VIRTUAL_KEY is not set (load it with the documented secret procedure; never paste it)")
    return key


def embed(texts: list[str], model: str, gateway: str, key: str) -> list[list[float]]:
    """One text per request (EMBED_PARALLEL at a time, rate limits retried), results returned in input order.

    Never batch: the course gateway (LiteLLM proxy) returns batched embeddings in the WRONG ORDER
    when a batch mixes cached and uncached inputs — each vector then belongs to a neighbouring
    text. A single-input request cannot be misordered."""
    def one(text: str) -> list[float]:
        with httpx.Client(timeout=60) as client:
            response = _post_with_retry(client, f"{gateway}/embeddings", {"model": model, "input": [text]}, key)
        if response.status_code != 200:
            raise RagError(f"gateway HTTP {response.status_code} for model {model!r}: {_mask(response.text, key)[:300]}")
        data = response.json()["data"]
        if len(data) != 1:
            raise RagError(f"gateway returned {len(data)} vectors for 1 input")
        return data[0]["embedding"]
    if os.environ.get("RAG_QUALIFICATION_BUDGET") is not None:
        # Serial execution stops before the next request after any failure: no queued work.
        return [one(text) for text in texts]
    with ThreadPoolExecutor(max_workers=EMBED_PARALLEL) as pool:
        return list(pool.map(one, texts))


def spot_check(texts: list[str], vectors: list[list[float]], model: str, gateway: str, key: str, n: int = 3) -> None:
    """Re-embed a few random texts and require the same vectors: catches a gateway/cache returning
    the wrong vector for a text before anything is written."""
    import random
    for i in random.sample(range(len(texts)), min(n, len(texts))):
        again = embed([texts[i]], model, gateway, key)[0]
        dot = sum(a * b for a, b in zip(again, vectors[i]))
        norm = (sum(a * a for a in again) * sum(b * b for b in vectors[i])) ** 0.5 or 1.0
        if dot / norm < 0.99:
            raise RagError(f"gateway returned an inconsistent embedding for chunk {i} (cosine {dot / norm:.3f} "
                           f"on re-embedding): refusing to build a candidate with misaligned vectors")


def _post_with_retry(client: httpx.Client, url: str, body: dict, key: str) -> httpx.Response:
    """Retry transient failures: timeouts/connection resets and 5xx (RETRIES attempts), and
    rate limiting — HTTP 429 that is NOT a budget error — with backoff honouring Retry-After
    (RATE_LIMIT_RETRIES attempts). Auth, alias and budget errors are returned at once."""
    if os.environ.get("RAG_QUALIFICATION_BUDGET") is not None:
        global _qualification_requests, _qualification_next_request
        try:
            budget = int(os.environ["RAG_QUALIFICATION_BUDGET"])
            interval = float(os.environ["RAG_QUALIFICATION_INTERVAL_SECONDS"])
            if budget <= 0 or not math.isfinite(interval) or interval <= 0:
                raise ValueError
        except (KeyError, ValueError) as exc:
            raise RagError("qualification requires a positive request budget and interval") from exc
        if _qualification_requests >= budget:
            raise RagError("qualification request budget exhausted; no request sent")
        time.sleep(max(0, _qualification_next_request - time.monotonic()))
        _qualification_requests += 1
        _qualification_next_request = time.monotonic() + interval
        try:
            return client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise RagError(f"qualification gateway failure: {type(exc).__name__}; no retry") from exc
    attempt = limited = 0
    while True:
        attempt += 1
        try:
            response = client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            if attempt >= RETRIES:
                raise RagError(f"gateway unreachable at {url.rsplit('/', 1)[0]} after {RETRIES} attempts: "
                               f"{type(exc).__name__}: {exc}") from exc
            print(f"  gateway {type(exc).__name__}; retry {attempt}/{RETRIES - 1}", file=sys.stderr)
            time.sleep(2 * attempt)
            continue
        if response.status_code == 429 and "budget" not in response.text.lower() and limited < RATE_LIMIT_RETRIES:
            limited += 1
            wait = float(response.headers.get("retry-after") or min(2 ** limited, 30))
            print(f"  gateway rate limit (429); waiting {wait:.0f}s ({limited}/{RATE_LIMIT_RETRIES})", file=sys.stderr)
            time.sleep(wait)
            continue
        if response.status_code >= 500 and attempt < RETRIES:
            print(f"  gateway HTTP {response.status_code}; retry {attempt}/{RETRIES - 1}", file=sys.stderr)
            time.sleep(2 * attempt)
            continue
        return response


def _mask(text: str, key: str) -> str:
    return text.replace(key, "sk-***") if key else text


# ------------------------------------------------------------------ Qdrant REST

class Qdrant:
    def __init__(self, url: str | None = None):
        self.url = (url or os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")).rstrip("/")
        headers = {"api-key": os.environ["QDRANT_API_KEY"]} if os.environ.get("QDRANT_API_KEY") else {}
        self.http = httpx.Client(base_url=self.url, timeout=60, headers=headers)

    def call(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            hint = (" — is the port-forward running? kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333"
                    if "127.0.0.1" in self.url or "localhost" in self.url
                    else " — is the workbench-qdrant pod Running? kubectl -n workbench get pods")
            raise RagError(f"Qdrant unreachable at {self.url} ({type(exc).__name__}){hint}") from exc
        if response.status_code >= 400:
            raise RagError(f"Qdrant {method} {path}: HTTP {response.status_code} {response.text[:300]}")
        return response.json().get("result", {})

    def aliases(self) -> dict[str, str]:
        return {a["alias_name"]: a["collection_name"] for a in self.call("GET", "/aliases")["aliases"]}

    def exists(self, name: str) -> bool:
        return bool(self.call("GET", f"/collections/{name}/exists")["exists"])

    def resolve(self, name: str) -> str:
        """Physical collection behind ``name`` (an alias or a collection)."""
        return self.aliases().get(name, name)

    def recreate(self, name: str, dimension: int) -> None:
        if self.exists(name):
            self.call("DELETE", f"/collections/{name}")
        self.call("PUT", f"/collections/{name}", json={"vectors": {"size": dimension, "distance": "Cosine"}})

    def delete(self, name: str) -> None:
        self.call("DELETE", f"/collections/{name}")

    def upsert(self, name: str, points: list[dict]) -> None:
        for start in range(0, len(points), 64):
            self.call("PUT", f"/collections/{name}/points", params={"wait": "true"},
                      json={"points": points[start:start + 64]})

    def count(self, name: str) -> int:
        return self.call("POST", f"/collections/{name}/points/count", json={"exact": True})["count"]

    def query(self, name: str, vector: list[float], limit: int) -> list[dict]:
        return self.call("POST", f"/collections/{name}/points/query",
                         json={"query": vector, "limit": limit, "with_payload": True})["points"]

    def sample_payload(self, name: str) -> dict:
        points = self.call("POST", f"/collections/{name}/points/scroll",
                           json={"limit": 1, "with_payload": True, "with_vector": False})["points"]
        return points[0]["payload"] if points else {}


def check_writable(qdrant: Qdrant, collection: str, prefix: str) -> str:
    """Ingestion writes only disposable candidates named ``<prefix>_<suffix>``: never an alias
    and never a protected fixture. Returns the target state: "new", "exists" (an unpromoted
    candidate) or "live" (the collection behind an alias; ingest.py may only reuse it)."""
    if not NAME.fullmatch(collection):
        raise RagError(f"invalid collection name {collection!r}")
    if collection in PROTECTED:
        raise RagError(f"refusing to write {collection!r}: protected fixture (S10 monitoring), never modified by ingestion")
    if collection == prefix:
        raise RagError(f"refusing to write {collection!r}: that is the LIVE alias; ingest a candidate "
                       f"({prefix}_manual or {prefix}_<SHA>) and promote it with scripts/promote-corpus.sh")
    if not collection.startswith(prefix + "_"):
        raise RagError(f"refusing to write {collection!r}: candidates must be named {prefix}_<suffix>")
    aliases = qdrant.aliases()
    if collection in aliases:
        raise RagError(f"refusing to write {collection!r}: it is an alias (-> {aliases[collection]})")
    if collection in aliases.values():
        return "live"
    return "exists" if qdrant.exists(collection) else "new"


PROVENANCE_KEYS = ("corpus_hash", "corpus_revision", "corpus_chunks", "embedding_model",
                   "settings_hash", "ingestion_source_hash")


def provenance_diff(qdrant: Qdrant, collection: str, planned: dict) -> list[str]:
    """Differences between a stored candidate and the planned inputs ([] = same identity)."""
    stored = qdrant.sample_payload(collection)
    if not stored:
        return ["no stored provenance (empty collection)"]
    diff = [f"{k}: stored {stored.get(k)!r} != planned {planned[k]!r}"
            for k in PROVENANCE_KEYS if stored.get(k) != planned[k]]
    count = qdrant.count(collection)
    if count != planned["corpus_chunks"]:
        diff.append(f"points: stored {count} != planned {planned['corpus_chunks']}")
    return diff


# ------------------------------------------------------------------ provenance

def sha256_files(paths: list[Path]) -> str:
    manifest = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.as_posix()}\n" for p in sorted(paths))
    return hashlib.sha256(manifest.encode()).hexdigest()


def git_revision(paths: list[str]) -> str:
    """HEAD SHA, suffixed ``+dirty`` when the given paths have uncommitted changes and
    ``+external`` when an input lies outside the repository (so it is not versioned)."""
    root = Path.cwd().resolve()
    inside = [p for p in paths if Path(p).resolve() == root or root in Path(p).resolve().parents]
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", *inside],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("+dirty" if dirty else "") + ("+external" if len(inside) < len(paths) else "")


def point_id(source: str, index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}#{index}"))


def verify_complete(qdrant: Qdrant, collection: str) -> dict:
    """Return the candidate's provenance; refuse empty or partial collections."""
    physical = qdrant.resolve(collection)
    if not qdrant.exists(physical):
        raise RagError(f"collection {collection!r} does not exist")
    payload = qdrant.sample_payload(physical)
    count = qdrant.count(physical)
    expected = payload.get("corpus_chunks")
    if not expected or count != expected:
        raise RagError(f"collection {collection!r} is INCOMPLETE ({count} points, expected {expected}); "
                       "it is not a usable candidate — re-run ingestion")
    return {"collection": collection, "physical": physical, "points": count,
            **{k: payload.get(k) for k in ("corpus_hash", "corpus_revision", "embedding_model",
                                          "settings_hash", "ingestion_source_hash")}}


def retrieve(qdrant: Qdrant, collection: str, question: str, top_k: int, contract: dict, key: str) -> list[dict]:
    """Embed the question with the FIXED query alias and return the top_k payloads + scores."""
    vector = embed([question], contract["query_model"], contract["gateway"], key)[0]
    return [{"score": hit["score"], **hit["payload"]} for hit in qdrant.query(collection, vector, top_k)]
