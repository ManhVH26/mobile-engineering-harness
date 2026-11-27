"""Read harness run state for the Control Room page.

Primary source: ``<project>/.harness/run/<run-id>/state.json`` + events.jsonl +
gates/ (the Control Room contract). Fallback: scan the artifacts the harness
already writes today (``plans/<date>-<slug>/plan.md`` with a ``Status:`` line,
``plans/reports/*.md``, ``briefs/<slug>/brief.yaml``) so a run shows progress
even before any emit hook is wired.
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone, timedelta

_SAIGON = timezone(timedelta(hours=7))


def _now() -> str:
    return datetime.now(_SAIGON).replace(microsecond=0).isoformat()


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def run_root(project: str) -> str:
    return os.path.join(project, ".harness", "run")


# --- contract runs ---------------------------------------------------------

def list_contract_runs(project: str):
    root = run_root(project)
    if not os.path.isdir(root):
        return []
    runs = []
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not os.path.isdir(d) or name == "bugs":
            continue
        state = _read_json(os.path.join(d, "state.json"))
        if state is None:
            continue
        state.setdefault("run_id", name)
        state["source"] = "contract"
        runs.append(state)
    return runs


def read_events(project: str, run_id: str, after: int = 0):
    path = os.path.join(run_root(project), run_id, "events.jsonl")
    out = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i < after:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                ev["seq"] = i
                out.append(ev)
    except FileNotFoundError:
        pass
    return out


def pending_gates(project: str, run_id: str):
    gdir = os.path.join(run_root(project), run_id, "gates")
    out = []
    if not os.path.isdir(gdir):
        return out
    for f in sorted(glob.glob(os.path.join(gdir, "*.json"))):
        if f.endswith(".answer.json"):
            continue
        gate = _read_json(f)
        if gate and gate.get("status") == "pending":
            out.append(gate)
    return out


def read_bugs(project: str):
    bugs = {}
    # project-level bug lists live under any contract run's bugs/, plus a
    # shared .harness/run/bugs/ pool for panel refreshes not tied to a run.
    patterns = [
        os.path.join(run_root(project), "*", "bugs", "*.json"),
        os.path.join(run_root(project), "bugs", "*.json"),
    ]
    for pat in patterns:
        for f in glob.glob(pat):
            data = _read_json(f)
            if not data:
                continue
            items = data.get("bugs") if isinstance(data, dict) else data
            if isinstance(items, dict):
                items = list(items.values())
            for b in (items or []):
                key = b.get("key") or b.get("id") or b.get("url")
                if key:
                    bugs[key] = b
    return list(bugs.values())


# --- fallback scan of today's harness artifacts ----------------------------

_STATUS_RE = re.compile(r"(?im)^\s*Status\s*[:：]\s*(.+?)\s*$")
_PLAN_DIR_RE = re.compile(r"^(\d{6})-(\d{4})-(.+)$")


def _status_from_md(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            head = fh.read(4000)
    except OSError:
        return None
    m = _STATUS_RE.search(head)
    return m.group(1).strip() if m else None


def _norm_status(raw):
    if not raw:
        return "running"
    low = raw.lower()
    if any(k in low for k in ("verified", "done", "approve", "ready", "merged", "implemented")):
        return "done"
    if any(k in low for k in ("blocked", "fail")):
        return "blocked"
    return "running"


def scan_fallback_runs(project: str):
    """Build read-only pseudo-runs from plans/ + briefs/ the harness already writes."""
    runs = []
    plans_dir = os.path.join(project, "plans")
    if os.path.isdir(plans_dir):
        for name in sorted(os.listdir(plans_dir), reverse=True):
            d = os.path.join(plans_dir, name)
            plan_md = os.path.join(d, "plan.md")
            if not os.path.isfile(plan_md):
                continue
            m = _PLAN_DIR_RE.match(name)
            slug = m.group(3) if m else name
            raw = _status_from_md(plan_md)
            stages = [{"id": "plan", "name": "Plan", "agent": "architect",
                       "status": "done", "artifact": os.path.relpath(plan_md, project),
                       "updated_at": _file_mtime(plan_md)}]
            # phase-*.md files => sub-stages
            for ph in sorted(glob.glob(os.path.join(d, "phase-*.md"))):
                pstatus = _norm_status(_status_from_md(ph))
                stages.append({"id": os.path.basename(ph)[:-3], "name": os.path.basename(ph)[:-3],
                               "agent": "coder", "status": pstatus,
                               "artifact": os.path.relpath(ph, project),
                               "updated_at": _file_mtime(ph)})
            report = _find_report(project, slug)
            if report:
                stages.append({"id": "report", "name": "Report", "agent": "reviewer",
                               "status": _norm_status(_status_from_md(report)),
                               "artifact": os.path.relpath(report, project),
                               "updated_at": _file_mtime(report)})
            runs.append({
                "run_id": name, "kind": "feature", "slug": slug,
                "title": _first_heading(plan_md) or slug,
                "status": _norm_status(raw), "source": "fallback",
                "updated_at": _file_mtime(plan_md), "stages": stages,
                "workers": [], "gates_pending": [],
            })
    return runs


def _file_mtime(path: str):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), _SAIGON).replace(
            microsecond=0).isoformat()
    except OSError:
        return _now()


def _first_heading(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("#"):
                    return line.lstrip("# ").strip()
    except OSError:
        pass
    return None


def _find_report(project: str, slug: str):
    reports = os.path.join(project, "plans", "reports")
    if not os.path.isdir(reports):
        return None
    cands = [f for f in glob.glob(os.path.join(reports, "*.md")) if slug in os.path.basename(f)]
    return sorted(cands)[-1] if cands else None


def list_runs(project: str):
    """All runs: contract runs first (live), then fallback scans not shadowed."""
    contract = list_contract_runs(project)
    seen = {r["run_id"] for r in contract}
    fallback = [r for r in scan_fallback_runs(project) if r["run_id"] not in seen]
    runs = contract + fallback
    runs.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
    return runs


def get_run(project: str, run_id: str):
    for r in list_runs(project):
        if r["run_id"] == run_id:
            r["events"] = read_events(project, run_id)
            r["gates"] = pending_gates(project, run_id)
            return r
    return None
