"""S10 synthetic Qdrant workload (MON-05) — monitoring traffic, not RAG.

Run from the ai-workbench root with a Qdrant port-forward open
(`kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333`):

  uv run --project monitoring --locked python scripts/qdrant-load.py --seed
  uv run --project monitoring --locked python scripts/qdrant-load.py --queries 120
  uv run --project monitoring --locked python scripts/qdrant-load.py --cleanup   # optional

--seed      (re)creates ONLY the `monitoring_demo` collection: 4-dimensional
            vectors from a fixed seed, POINTS points -> collections_vector_total rises.
--queries N N search+count round trips (2N REST calls) against monitoring_demo ->
            rest_responses_total / rest_responses_avg_duration_seconds move;
            the point count must stay the same (read-only load).
--cleanup   deletes ONLY monitoring_demo.

No embedding model, no gateway, no course key. Every other collection and alias
(e.g. S12's study_guides) is snapshotted before and verified unchanged after;
any change, a missing demo collection, or an unreachable Qdrant exits nonzero.
Env: QDRANT_URL (default http://localhost:6333).
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

import httpx

COLLECTION = "monitoring_demo"
DIM = 4
POINTS = 500
SEED = 1010  # S10


def vectors(n: int, seed: int) -> list[list[float]]:
    rnd = random.Random(seed)
    return [[round(rnd.uniform(-1, 1), 6) for _ in range(DIM)] for _ in range(n)]


class Qdrant:
    def __init__(self, url: str):
        self.c = httpx.Client(base_url=url, timeout=10)

    def req(self, method: str, path: str, **kw) -> dict:
        r = self.c.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    def exists(self, name: str) -> bool:
        return self.req("GET", f"/collections/{name}/exists")["result"]["exists"]

    def count(self, name: str) -> int:
        return self.req("POST", f"/collections/{name}/points/count", json={"exact": True})["result"]["count"]

    def snapshot_others(self) -> dict:
        """Every collection except ours (with exact point counts) + every alias."""
        cols = [c["name"] for c in self.req("GET", "/collections")["result"]["collections"]]
        state = {f"collection:{c}": self.count(c) for c in sorted(cols) if c != COLLECTION}
        for a in self.req("GET", "/aliases")["result"]["aliases"]:
            state[f"alias:{a['alias_name']}"] = a["collection_name"]
        return state


def seed(q: Qdrant) -> None:
    if q.exists(COLLECTION):
        q.req("DELETE", f"/collections/{COLLECTION}")
    q.req("PUT", f"/collections/{COLLECTION}", json={"vectors": {"size": DIM, "distance": "Cosine"}})
    vecs = vectors(POINTS, SEED)
    for start in range(0, POINTS, 100):
        pts = [{"id": i, "vector": vecs[i], "payload": {"i": i}} for i in range(start, min(start + 100, POINTS))]
        q.req("PUT", f"/collections/{COLLECTION}/points", params={"wait": "true"}, json={"points": pts})
    n = q.count(COLLECTION)
    if n != POINTS:
        raise RuntimeError(f"seeded {n} points, expected {POINTS}")
    print(f"seed: {COLLECTION} reset with {n} deterministic {DIM}-d points (seed {SEED})")


def queries(q: Qdrant, n: int) -> None:
    if not q.exists(COLLECTION):
        raise RuntimeError(f"{COLLECTION} does not exist — run --seed first")
    before = q.count(COLLECTION)
    qv = vectors(n, SEED + 1)
    t0 = time.monotonic()
    for v in qv:
        hits = q.req("POST", f"/collections/{COLLECTION}/points/query", json={"query": v, "limit": 3})
        if not hits["result"]["points"]:
            raise RuntimeError("query returned no points")
        q.count(COLLECTION)
    dt = time.monotonic() - t0
    after = q.count(COLLECTION)
    if after != before:
        raise RuntimeError(f"read-only load changed the point count {before} -> {after}")
    print(f"queries: {n} query+count pairs ({2 * n} REST calls) in {dt:.1f}s; "
          f"points unchanged at {after}")


def cleanup(q: Qdrant) -> None:
    if q.exists(COLLECTION):
        q.req("DELETE", f"/collections/{COLLECTION}")
        print(f"cleanup: deleted {COLLECTION}")
    else:
        print(f"cleanup: {COLLECTION} already absent")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seed", action="store_true")
    g.add_argument("--queries", type=int, metavar="N")
    g.add_argument("--cleanup", action="store_true")
    a = ap.parse_args()
    if a.queries is not None and a.queries < 1:
        ap.error("--queries N needs N >= 1")
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    q = Qdrant(url)
    try:
        others = q.snapshot_others()
        if a.seed:
            seed(q)
        elif a.cleanup:
            cleanup(q)
        else:
            queries(q, a.queries)
        if q.snapshot_others() != others:
            raise RuntimeError("another collection or alias changed during the run")
        print(f"preserved: {len(others)} other collection(s)/alias(es) unchanged")
        return 0
    except httpx.TransportError as e:
        print(f"ERROR: Qdrant unreachable at {url} ({type(e).__name__}) — is the port-forward "
              "running? kubectl -n workbench port-forward svc/workbench-qdrant 6333:6333", file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
