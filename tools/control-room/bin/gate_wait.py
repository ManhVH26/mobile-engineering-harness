#!/usr/bin/env python3
"""gate_wait.py — block until the owner answers a gate on the Control Room page.

Polls gates/<id>.answer.json. On answer, prints the answer JSON to stdout and
exits 0. On timeout exits 2 (the worker can then fall back to asking in chat).

Usage:
  gate_wait.py <run_dir> <gate_id> [--timeout 3600] [--interval 2]

The worker reads the printed JSON: {"option_id": "...", "note": "..."}.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _store  # noqa: E402


def wait_for_answer(run_dir: str, gate_id: str, timeout: float, interval: float,
                    sleep=time.sleep, clock=time.monotonic):
    answer_path = os.path.join(run_dir, "gates", gate_id + ".answer.json")
    deadline = clock() + timeout
    while True:
        ans = _store.read_json(answer_path, None)
        if ans is not None:
            return ans
        if clock() >= deadline:
            return None
        sleep(interval)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="gate_wait.py")
    p.add_argument("run_dir")
    p.add_argument("gate_id")
    p.add_argument("--timeout", type=float, default=3600.0)
    p.add_argument("--interval", type=float, default=2.0)
    args = p.parse_args(argv)

    ans = wait_for_answer(args.run_dir, args.gate_id, args.timeout, args.interval)
    if ans is None:
        sys.stderr.write("gate_wait: timed out waiting for %s\n" % args.gate_id)
        return 2
    # Mark the gate resolved + drop from pending (best effort). Idempotent: if
    # the server already flipped it to answered, don't emit a duplicate event.
    try:
        gate_path = os.path.join(args.run_dir, "gates", args.gate_id + ".json")
        gate = _store.read_json(gate_path, None)
        already = bool(gate and gate.get("status") == "answered")
        if gate is not None and not already:
            gate["status"] = "answered"
            gate["answer"] = ans
            _store.write_json_atomic(gate_path, gate)
            _store.update_state(args.run_dir, lambda st: st.update(
                {"gates_pending": [g for g in (st.get("gates_pending") or [])
                                   if g != args.gate_id]}) or st)
            _store.append_event(args.run_dir, {
                "type": "gate_answered", "level": "gate",
                "msg": ans.get("option_id", ""), "ref": args.gate_id})
    except Exception as exc:  # pragma: no cover
        sys.stderr.write("gate_wait warning: %s\n" % exc)
    sys.stdout.write(json.dumps(ans, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
