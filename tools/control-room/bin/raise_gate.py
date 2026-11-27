#!/usr/bin/env python3
"""raise_gate.py — a spawned worker raises a decision gate for the owner.

Writes gates/<id>.json (status=pending) and appends a gate_raised event. The
worker then calls gate_wait.py to block until the owner answers on the page.

Usage:
  raise_gate.py <run_dir> --id g-plan-1 --kind approval \
      --title "Duyệt plan?" --question "Plan đụng 8 file. APPROVE?" \
      --option approve:APPROVE --option request_changes:"REQUEST CHANGES" \
      [--allow-freeform] [--context-ref plans/.../plan.md] [--raised-by architect]

Prints the gate id on stdout.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _store  # noqa: E402


def parse_option(raw: str) -> dict:
    if ":" in raw:
        oid, label = raw.split(":", 1)
    else:
        oid, label = raw, raw
    return {"id": oid.strip(), "label": label.strip()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="raise_gate.py")
    p.add_argument("run_dir")
    p.add_argument("--id", required=True)
    p.add_argument("--kind", default="approval")
    p.add_argument("--title", required=True)
    p.add_argument("--question", default="")
    p.add_argument("--option", action="append", default=[],
                   help="id:Label (repeatable)")
    p.add_argument("--allow-freeform", action="store_true")
    p.add_argument("--context-ref", action="append", default=[])
    p.add_argument("--raised-by", default="worker")
    args = p.parse_args(argv)

    options = [parse_option(o) for o in args.option] or [
        {"id": "ok", "label": "OK"}]
    gate = {
        "id": args.id,
        "run_id": os.path.basename(os.path.normpath(args.run_dir)),
        "kind": args.kind,
        "title": args.title,
        "question": args.question,
        "options": options,
        "allow_freeform": bool(args.allow_freeform),
        "context_refs": args.context_ref,
        "raised_by": args.raised_by,
        "raised_at": _store.now_iso(),
        "status": "pending",
    }
    _store.ensure_run_dir(args.run_dir)
    _store.write_json_atomic(
        os.path.join(args.run_dir, "gates", args.id + ".json"), gate)
    _store.update_state(args.run_dir, lambda st: st.update(
        {"gates_pending": sorted(set((st.get("gates_pending") or []) + [args.id]))}) or st)
    _store.append_event(args.run_dir, {
        "type": "gate_raised", "level": "gate", "msg": args.title,
        "worker": args.raised_by, "ref": args.id})
    sys.stdout.write(args.id + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
