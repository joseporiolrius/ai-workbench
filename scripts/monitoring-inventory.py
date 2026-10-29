#!/usr/bin/env python3
"""S10 monitoring inventory gate (MON-01).

Reads course-artifacts.yaml (the single source of chart versions and image
pins) and refuses to let anything be installed that is not pinned and approved.

  monitoring-inventory.py check [--release R]   # render + verify every image
  monitoring-inventory.py helm-args RELEASE     # args for `helm upgrade --install`
  monitoring-inventory.py evidence              # (on the VM) pulled digests + arch

`check` pulls each chart at its pinned version (verifying the .tgz sha256
against chart_digest), renders it with the committed values plus the manifest's
image overrides, and walks EVERY pod template (containers, initContainers,
ephemeralContainers; Deployments, StatefulSets, DaemonSets, Jobs, CronJobs,
Pods incl. helm hooks/tests). Each rendered image must be an approved mirror
record with matching tag and digest; each disabled optional workload must not
render. Any missing pin, placeholder, unapproved image or unexpected workload
exits nonzero BEFORE installation.

Needs: helm, python3 + PyYAML (present on Ubuntu 24.04 via cloud-init).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "course-artifacts.yaml"
CHART_CACHE = Path(os.environ.get("MONITORING_CHART_CACHE",
                                  Path.home() / ".cache" / "ai-workbench" / "charts"))
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PLACEHOLDERS = {"", "tbd", "todo", "pending", "latest", "null", "none", "xxx", "changeme"}
MUTABLE_TAGS = {"latest", "main", "master", "head", "stable", "edge", "nightly"}
# Only used to satisfy `required` in prometheus-values.yaml during a render check.
RENDER_PROBE_URL = "https://wb.a000.dbai24.i40sys.com/"


class InventoryError(Exception):
    pass


def placeholder(v) -> bool:
    return v is None or str(v).strip().lower() in PLACEHOLDERS or str(v).startswith("sha256:000")


def split_ref(ref: str):
    """'reg/repo:tag@sha256:x' -> (repo, tag|None, digest|None)."""
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    tag = None
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        ref, tag = ref.rsplit(":", 1)
    return ref, tag, digest


# ----------------------------------------------------------------- manifest
def load_manifest(path: Path = MANIFEST) -> dict:
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict) or "monitoring" not in doc or "artifacts" not in doc:
        raise InventoryError(f"{path}: missing monitoring/artifacts sections")
    return doc


def validate_pins(doc: dict) -> list[str]:
    """Static pin checks — no network. Every referenced record fully pinned."""
    errs: list[str] = []
    mon = doc["monitoring"]
    reg = str(mon.get("approved_registry", "")).rstrip("/")
    if placeholder(reg):
        errs.append("monitoring.approved_registry is not set")
    arts = {a.get("id"): a for a in doc["artifacts"] if isinstance(a, dict)}
    for rel in mon.get("releases") or []:
        name = rel.get("release", "?")
        crec = arts.get(rel.get("chart"))
        if not crec or crec.get("kind") != "monitoring_chart":
            errs.append(f"{name}: chart record {rel.get('chart')!r} missing")
        else:
            ident = crec.get("identity") or {}
            for f in ("chart", "repo_url", "chart_version", "chart_digest", "image_digest"):
                if placeholder(ident.get(f)):
                    errs.append(f"{name}: chart pin '{f}' missing/placeholder ({ident.get(f)!r})")
            for f in ("chart_digest", "image_digest"):
                if not placeholder(ident.get(f)) and not DIGEST_RE.match(str(ident.get(f))):
                    errs.append(f"{name}: chart '{f}' is not sha256:<64hex>")
        if not (ROOT / str(rel.get("values", ""))).is_file():
            errs.append(f"{name}: values file {rel.get('values')!r} not found")
        if not rel.get("image_overrides"):
            errs.append(f"{name}: no image_overrides (every enabled image must be pinned)")
        for ov in rel.get("image_overrides") or []:
            irec = arts.get(ov.get("image"))
            if not irec or irec.get("kind") != "monitoring_image":
                errs.append(f"{name}: image record {ov.get('image')!r} missing")
                continue
            ident = irec.get("identity") or {}
            ref, dig = ident.get("image_ref"), ident.get("digest")
            if placeholder(ref) or placeholder(dig):
                errs.append(f"{ov['image']}: image_ref/digest missing or placeholder")
                continue
            repo, tag, _ = split_ref(str(ref))
            if not repo.startswith(reg + "/"):
                errs.append(f"{ov['image']}: {ref} is not in approved registry {reg}")
            if not tag or tag.lower() in MUTABLE_TAGS:
                errs.append(f"{ov['image']}: {ref} has no fixed tag")
            if not DIGEST_RE.match(str(dig)):
                errs.append(f"{ov['image']}: digest {dig!r} is not sha256:<64hex>")
            s = ov.get("set") or {}
            for f in ("repository", "tag", "digest"):
                if not s.get(f):
                    errs.append(f"{ov['image']}: override path for '{f}' missing")
    return errs


def override_sets(doc: dict, rel: dict) -> list[str]:
    """--set pairs that point every image at its pinned mirror."""
    arts = {a["id"]: a for a in doc["artifacts"]}
    pairs = []
    for ov in rel["image_overrides"]:
        ident = arts[ov["image"]]["identity"]
        repo, tag, _ = split_ref(ident["image_ref"])
        digest = ident["digest"]
        if ov.get("digest_format") == "hex":
            digest = digest.split(":", 1)[1]
        s = ov["set"]
        if s.get("registry"):
            registry, _, path = repo.partition("/")
            pairs += [f"{s['registry']}={registry}", f"{s['repository']}={path}"]
        else:
            pairs.append(f"{s['repository']}={repo}")
        pairs += [f"{s['tag']}={tag}", f"{s['digest']}={digest}"]
    return pairs


# -------------------------------------------------------------------- charts
def chart_tgz(ident: dict) -> Path:
    """Pinned chart .tgz from the local cache, verified against chart_digest."""
    CHART_CACHE.mkdir(parents=True, exist_ok=True)
    tgz = CHART_CACHE / f"{ident['chart']}-{ident['chart_version']}.tgz"
    if not tgz.exists():
        r = subprocess.run(["helm", "pull", ident["chart"], "--repo", ident["repo_url"],
                            "--version", str(ident["chart_version"]),
                            "--destination", str(CHART_CACHE)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise InventoryError(f"helm pull {ident['chart']} {ident['chart_version']} failed: "
                                 f"{r.stderr.strip()}")
    got = "sha256:" + hashlib.sha256(tgz.read_bytes()).hexdigest()
    if got != ident["chart_digest"]:
        raise InventoryError(f"{tgz.name}: digest {got} != pinned {ident['chart_digest']} "
                             "(chart changed upstream or cache corrupted)")
    return tgz


def release_record(doc: dict, name: str) -> dict:
    for rel in doc["monitoring"]["releases"]:
        if rel["release"] == name:
            return rel
    raise InventoryError(f"unknown release {name!r}")


def helm_args(doc: dict, name: str) -> list[str]:
    rel = release_record(doc, name)
    arts = {a["id"]: a for a in doc["artifacts"]}
    ident = arts[rel["chart"]]["identity"]
    args = [str(chart_tgz(ident)), "--namespace", doc["monitoring"]["namespace"],
            "-f", str(ROOT / rel["values"])]
    # Optional extra values layered on top (e.g. the S10 homework Grafana route):
    # MONITORING_EXTRA_VALUES_<RELEASE>=file[:file...]. They pass through the
    # same render check, so they cannot smuggle in an unapproved image.
    for extra in filter(None, os.environ.get(f"MONITORING_EXTRA_VALUES_{name.upper()}", "").split(":")):
        path = Path(extra) if Path(extra).is_absolute() else ROOT / extra
        if not path.is_file():
            raise InventoryError(f"extra values file {extra!r} not found")
        args += ["-f", str(path)]
    for p in override_sets(doc, rel):
        args += ["--set", p]
    return args


# ------------------------------------------------------------------- render
POD_PATHS = {
    "Pod": ["spec"],
    "Deployment": ["spec", "template", "spec"],
    "StatefulSet": ["spec", "template", "spec"],
    "DaemonSet": ["spec", "template", "spec"],
    "ReplicaSet": ["spec", "template", "spec"],
    "Job": ["spec", "template", "spec"],
    "CronJob": ["spec", "jobTemplate", "spec", "template", "spec"],
}


IMAGE_LINE = re.compile(r"^\s*-?\s*image:\s*[\"']?([^\s\"']+)", re.M)


def rendered_workloads(manifest_text: str) -> list[tuple[str, str, str, str]]:
    """[(Kind/name, container, image, section)] for every pod template.

    Fails closed: a rendered document that is not parseable YAML still has its
    image: lines reported (as an UNPARSEABLE workload) so it cannot slip past.
    """
    out = []
    for raw in re.split(r"^---\s*$", manifest_text, flags=re.M):
        try:
            d = yaml.safe_load(raw)
        except yaml.YAMLError:
            src = re.search(r"^# Source: (.+)$", raw, re.M)
            who = f"UNPARSEABLE/{src.group(1) if src else '?'}"
            for img in IMAGE_LINE.findall(raw) or ["<unparseable document>"]:
                out.append((who, "?", img, "unparseable"))
            continue
        if not isinstance(d, dict) or d.get("kind") not in POD_PATHS:
            continue
        spec = d
        for k in POD_PATHS[d["kind"]]:
            spec = (spec or {}).get(k) or {}
        who = f"{d['kind']}/{d.get('metadata', {}).get('name')}"
        for section in ("initContainers", "containers", "ephemeralContainers"):
            for c in spec.get(section) or []:
                out.append((who, c.get("name"), c.get("image"), section))
    return out


def render(doc: dict, name: str, extra_sets: list[str] | None = None) -> str:
    args = helm_args(doc, name)
    cmd = ["helm", "template", name, *args, "--set", f"workbenchProbe.url={RENDER_PROBE_URL}"]
    for p in extra_sets or []:
        cmd += ["--set", p]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise InventoryError(f"helm template {name} failed: {r.stderr.strip()}")
    return r.stdout


def check_release(doc: dict, name: str, extra_sets=None, quiet=False) -> list[str]:
    errs: list[str] = []
    rel = release_record(doc, name)
    arts = {a["id"]: a for a in doc["artifacts"]}
    approved = {}
    for ov in rel["image_overrides"]:
        ident = arts[ov["image"]]["identity"]
        repo, tag, _ = split_ref(ident["image_ref"])
        approved[repo] = (tag, ident["digest"], ov["image"])
    workloads = rendered_workloads(render(doc, name, extra_sets))
    if not workloads:
        errs.append(f"{name}: rendered no workloads")
    for who, cname, image, section in workloads:
        repo, tag, digest = split_ref(str(image))
        ok = repo in approved and digest == approved[repo][1] and tag in (None, approved[repo][0])
        if not quiet:
            print(f"  {'OK ' if ok else 'BAD'} {name:<10} {who:<48} {section:<14} {cname:<28} {image}")
        if section == "unparseable":
            errs.append(f"{name}: rendered document {who} is not valid YAML (fails closed); "
                        f"image seen: {image}")
        elif repo not in approved:
            errs.append(f"{name}: {who} {section}/{cname} uses UNAPPROVED image {image}")
        elif digest is None:
            errs.append(f"{name}: {who} {cname} image {image} is not pinned by digest")
        elif digest != approved[repo][1]:
            errs.append(f"{name}: {who} {cname} digest {digest} != pinned {approved[repo][1]}")
        elif tag not in (None, approved[repo][0]):
            errs.append(f"{name}: {who} {cname} tag {tag} != pinned {approved[repo][0]}")
    strings = [f"{w}/{c}={i}" for w, c, i, _ in workloads]
    for dis in doc["monitoring"].get("disabled_workloads") or []:
        if dis.get("release") != name:
            continue
        hits = [s for s in strings if re.search(dis["absent"], s)]
        if hits:
            errs.append(f"{name}: disabled workload '{dis['workload']}' renders: {hits}")
        elif not quiet:
            print(f"  --- {name:<10} disabled: {dis['workload']} ({dis['switch']})")
    return errs


# --------------------------------------------------------------- evidence
def evidence(doc: dict) -> int:
    """On the VM: compare what the kubelet actually pulled with the pins."""
    ns = doc["monitoring"]["namespace"]
    arts = {a["id"]: a for a in doc["artifacts"] if a.get("kind") == "monitoring_image"}
    pinned = {split_ref(a["identity"]["image_ref"])[0]: a["identity"]["digest"] for a in arts.values()}
    pods = json.loads(subprocess.run(["kubectl", "-n", ns, "get", "pods", "-o", "json"],
                                     check=True, capture_output=True, text=True).stdout)
    nodes = json.loads(subprocess.run(["kubectl", "get", "nodes", "-o", "json"],
                                      check=True, capture_output=True, text=True).stdout)
    arch = {n["metadata"]["name"]: f"{n['status']['nodeInfo']['operatingSystem']}/"
                                   f"{n['status']['nodeInfo']['architecture']}" for n in nodes["items"]}
    bad = 0
    print(f"{'pod/container':<58} {'node platform':<14} pulled imageID")
    for p in pods["items"]:
        node = p["spec"].get("nodeName")
        for st in (p["status"].get("initContainerStatuses") or []) + (p["status"].get("containerStatuses") or []):
            # status.image may be a local config ID (sha256:…); the pulled repo@digest is imageID.
            repo, _, pulled = st.get("imageID", "").partition("@")
            ok = pinned.get(repo) == pulled
            bad += not ok
            print(f"{p['metadata']['name'] + '/' + st['name']:<58} {arch.get(node, '?'):<14} "
                  f"{'OK ' if ok else 'BAD'} {st.get('imageID')}")
    print("EVIDENCE:", "PASS" if not bad else f"FAIL ({bad} mismatches)")
    return 1 if bad else 0


# --------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--release")
    c.add_argument("--set", action="append", default=[], dest="extra",
                   help="extra value for a what-if render (e.g. enabling a disabled workload)")
    h = sub.add_parser("helm-args")
    h.add_argument("release")
    sub.add_parser("evidence")
    a = ap.parse_args()
    try:
        doc = load_manifest(a.manifest)
        errs = validate_pins(doc)
        if errs:
            print("INVENTORY: FAIL — incomplete chart/image pins (nothing installed)", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 2
        if a.cmd == "helm-args":
            print("\n".join(helm_args(doc, a.release)))
            return 0
        if a.cmd == "evidence":
            return evidence(doc)
        names = [a.release] if a.release else [r["release"] for r in doc["monitoring"]["releases"]]
        errs = []
        for n in names:
            errs += check_release(doc, n, a.extra)
        if errs:
            print("INVENTORY: FAIL", file=sys.stderr)
            for e in errs:
                print(f"  - {e}", file=sys.stderr)
            return 1
        print(f"INVENTORY: PASS — {', '.join(names)}: every rendered image is an approved "
              "pinned mirror; disabled workloads absent")
        return 0
    except InventoryError as e:
        print(f"INVENTORY: FAIL — {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
