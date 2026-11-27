"""Run-dir contract primitives (stdlib only, py3.9+).

A "run dir" is ``<project>/.harness/run/<run-id>/`` and holds:
  state.json            snapshot the page reads
  events.jsonl          append-only event log (SSE source)
  gates/<id>.json       a pending gate (agent -> page)
  gates/<id>.answer.json the owner's answer (page -> agent)
  bugs/<project>.json   Jira bug list for the Bug panel

These primitives are shared by the ``bin/`` worker scripts (emit / raise_gate /
gate_wait) and by the Control Room server. They are deliberately free of any
import from the harness so a spawned worker can call them with nothing but
``python3 <control-room>/bin/emit.py``.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta

# Asia/Saigon, matching harness convention (no external tz dependency).
_SAIGON = timezone(timedelta(hours=7))


def now_iso() -> str:
    return datetime.now(_SAIGON).replace(microsecond=0).isoformat()


def read_json(path: str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, ValueError):
        return default


def write_json_atomic(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def ensure_run_dir(run_dir: str) -> None:
    os.makedirs(os.path.join(run_dir, "gates"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "bugs"), exist_ok=True)


def state_path(run_dir: str) -> str:
    return os.path.join(run_dir, "state.json")


def events_path(run_dir: str) -> str:
    return os.path.join(run_dir, "events.jsonl")


# --- locking ---------------------------------------------------------------
try:
    import fcntl

    def _lock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
except ImportError:  # pragma: no cover - non-posix fallback
    def _lock(fh):
        pass

    def _unlock(fh):
        pass


def append_event(run_dir: str, event: dict) -> dict:
    """Append one event line. Returns the stored event (with ts filled)."""
    ensure_run_dir(run_dir)
    event = dict(event)
    event.setdefault("ts", now_iso())
    line = json.dumps(event, ensure_ascii=False)
    with open(events_path(run_dir), "a", encoding="utf-8") as fh:
        _lock(fh)
        try:
            fh.write(line + "\n")
        finally:
            _unlock(fh)
    return event


def update_state(run_dir: str, mutate) -> dict:
    """Read-modify-write state.json under an exclusive lock.

    ``mutate`` receives the current state dict and mutates it in place (or
    returns a new dict). The lock is held via a sidecar ``.state.lock`` file so
    the atomic replace of state.json itself is never on the locked handle.
    """
    ensure_run_dir(run_dir)
    lock_file = os.path.join(run_dir, ".state.lock")
    with open(lock_file, "a+", encoding="utf-8") as lh:
        _lock(lh)
        try:
            state = read_json(state_path(run_dir), {}) or {}
            result = mutate(state)
            if isinstance(result, dict):
                state = result
            state["updated_at"] = now_iso()
            write_json_atomic(state_path(run_dir), state)
            return state
        finally:
            _unlock(lh)


def upsert_stage(state: dict, stage: dict) -> dict:
    stages = state.setdefault("stages", [])
    for existing in stages:
        if existing.get("id") == stage.get("id"):
            existing.update({k: v for k, v in stage.items() if v is not None})
            existing["updated_at"] = now_iso()
            return state
    stage = {k: v for k, v in stage.items() if v is not None}
    stage.setdefault("status", "pending")
    stage["updated_at"] = now_iso()
    stages.append(stage)
    return state


def init_state(run_dir: str, run_id: str, kind: str, slug: str, title: str) -> dict:
    def mutate(state):
        state.setdefault("run_id", run_id)
        state.setdefault("kind", kind)
        state.setdefault("slug", slug)
        state.setdefault("title", title)
        state.setdefault("status", "running")
        state.setdefault("created_at", now_iso())
        state.setdefault("stages", [])
        state.setdefault("workers", [])
        return state

    return update_state(run_dir, mutate)
