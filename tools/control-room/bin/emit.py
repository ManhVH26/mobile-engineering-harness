#!/usr/bin/env python3
"""emit.py — a spawned worker uses this to report progress to the Control Room.

No-op friendly: if the run dir cannot be written, it exits 0 so it never breaks
a pipeline. Backward compatible — a harness run with no Control Room simply does
not call it.

Usage:
  emit.py <run_dir> init   --run-id ID --kind feature --slug S --title "T"
  emit.py <run_dir> stage  --id inspect --name Inspect --agent architect \
                           --status running [--artifact plans/.../plan.md] [--msg "..."]
  emit.py <run_dir> event  --type log --stage inspect --level info --msg "..." [--ref path]
  emit.py <run_dir> status --status done|blocked|failed [--msg "..."]
  emit.py <run_dir> worker --name coder --worktree ID --orca-ref ctx_.. --status working
  emit.py <run_dir> pr     --url https://... --state draft|ready|merged
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _store  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="emit.py")
    p.add_argument("run_dir")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--run-id", required=True)
    s.add_argument("--kind", default="feature")
    s.add_argument("--slug", default="")
    s.add_argument("--title", default="")

    s = sub.add_parser("stage")
    s.add_argument("--id", required=True)
    s.add_argument("--name", default=None)
    s.add_argument("--agent", default=None)
    s.add_argument("--status", default=None)
    s.add_argument("--artifact", default=None)
    s.add_argument("--msg", default=None)

    s = sub.add_parser("event")
    s.add_argument("--type", default="log")
    s.add_argument("--stage", default=None)
    s.add_argument("--worker", default=None)
    s.add_argument("--level", default="info")
    s.add_argument("--msg", default="")
    s.add_argument("--ref", default=None)

    s = sub.add_parser("status")
    s.add_argument("--status", required=True)
    s.add_argument("--msg", default=None)

    s = sub.add_parser("worker")
    s.add_argument("--name", required=True)
    s.add_argument("--worktree", default=None)
    s.add_argument("--orca-ref", default=None)
    s.add_argument("--status", default="working")

    s = sub.add_parser("pr")
    s.add_argument("--url", required=True)
    s.add_argument("--state", default="draft")

    args = p.parse_args(argv)
    run_dir = args.run_dir
    try:
        _store.ensure_run_dir(run_dir)
        if args.cmd == "init":
            _store.init_state(run_dir, args.run_id, args.kind, args.slug, args.title)
            _store.append_event(run_dir, {"type": "run_start", "level": "info",
                                          "msg": args.title or args.run_id})
        elif args.cmd == "stage":
            _store.update_state(run_dir, lambda st: _store.upsert_stage(st, {
                "id": args.id, "name": args.name, "agent": args.agent,
                "status": args.status, "artifact": args.artifact}))
            etype = {"running": "stage_start", "done": "stage_done"}.get(
                args.status or "", "stage_update")
            _store.append_event(run_dir, {"type": etype, "stage": args.id,
                                          "level": "info",
                                          "msg": args.msg or (args.name or args.id),
                                          "ref": args.artifact})
        elif args.cmd == "event":
            _store.append_event(run_dir, {"type": args.type, "stage": args.stage,
                                          "worker": args.worker, "level": args.level,
                                          "msg": args.msg, "ref": args.ref})
        elif args.cmd == "status":
            _store.update_state(run_dir, lambda st: st.update({"status": args.status}) or st)
            _store.append_event(run_dir, {"type": "run_" + args.status, "level": "info",
                                          "msg": args.msg or args.status})
        elif args.cmd == "worker":
            def mut(st):
                workers = st.setdefault("workers", [])
                for w in workers:
                    if w.get("name") == args.name:
                        w.update({"worktree": args.worktree, "orca_ref": args.orca_ref,
                                  "status": args.status})
                        return st
                workers.append({"name": args.name, "worktree": args.worktree,
                                "orca_ref": args.orca_ref, "status": args.status})
                return st
            _store.update_state(run_dir, mut)
            _store.append_event(run_dir, {"type": "worker_" + args.status,
                                          "worker": args.name, "level": "info",
                                          "msg": args.name})
        elif args.cmd == "pr":
            _store.update_state(run_dir, lambda st: st.update(
                {"pr": {"url": args.url, "state": args.state}}) or st)
            _store.append_event(run_dir, {"type": "pr", "level": "info",
                                          "msg": args.state, "ref": args.url})
    except Exception as exc:  # never break the pipeline on a telemetry error
        sys.stderr.write("emit.py warning: %s\n" % exc)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
