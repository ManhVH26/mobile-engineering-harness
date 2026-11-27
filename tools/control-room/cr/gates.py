"""Server-side gate answering: the page POSTs an answer, we write the file the
blocked worker's ``gate_wait.py`` is polling for.
"""
from __future__ import annotations

import os
import sys

_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
sys.path.insert(0, _BIN)
import _store  # noqa: E402


def answer_gate(project: str, run_id: str, gate_id: str, option_id: str,
                note: str = "", answered_by: str = "owner"):
    run_dir = os.path.join(project, ".harness", "run", run_id)
    gate_path = os.path.join(run_dir, "gates", gate_id + ".json")
    answer_path = os.path.join(run_dir, "gates", gate_id + ".answer.json")
    gate = _store.read_json(gate_path, None)
    if gate is None:
        return False, "gate not found"
    if gate.get("status") == "answered" or os.path.exists(answer_path):
        return False, "gate already answered"
    answer = {
        "gate_id": gate_id,
        "option_id": option_id,
        "note": note or "",
        "answered_by": answered_by,
        "answered_at": _store.now_iso(),
    }
    _store.write_json_atomic(
        os.path.join(run_dir, "gates", gate_id + ".answer.json"), answer)
    # Be authoritative so the page stops showing the gate immediately, even if
    # no worker is polling: flip the gate file, drop it from pending, emit once.
    # gate_wait.py is idempotent and will not re-emit when it sees this state.
    gate["status"] = "answered"
    gate["answer"] = answer
    _store.write_json_atomic(gate_path, gate)
    _store.update_state(run_dir, lambda st: st.update(
        {"gates_pending": [g for g in (st.get("gates_pending") or []) if g != gate_id]}) or st)
    _store.append_event(run_dir, {"type": "gate_answered", "level": "gate",
                                  "msg": option_id, "ref": gate_id})
    return True, answer
