#!/usr/bin/env python3
"""Seed a demo run so the page shows progress + a live gate with no Orca needed.

    python3 examples/seed_demo.py --project <repo-root>

Creates .harness/run/feature-book-detail-DEMO/ with a few stages, some events,
one pending gate, and a sample bug list for the Bug panel. Then you can:
  1) open the page, select the demo run, see progress (proof a),
  2) answer the gate on the page, and watch the "agent" continue (proof b) —
     run this script with --wait to simulate the blocked worker.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
import _store  # noqa: E402

RUN_ID = "feature-book-detail-DEMO"


def seed(project):
    run_dir = os.path.join(project, ".harness", "run", RUN_ID)
    _store.init_state(run_dir, RUN_ID, "feature", "book-detail",
                      "Book Detail — màn chi tiết sách (DEMO)")
    for sid, name, agent, status, art in [
        ("discovery", "Discovery", "product-analyst", "done", "briefs/book-detail/brief.yaml"),
        ("design", "Design", "designer", "done", "briefs/book-detail/design.md"),
        ("plan", "Plan", "architect", "done", "plans/261127-book-detail/plan.md"),
        ("implement", "Implement", "coder", "running", None),
    ]:
        _store.update_state(run_dir, lambda st, s=sid, n=name, a=agent, c=status, r=art:
                            _store.upsert_stage(st, {"id": s, "name": n, "agent": a,
                                                     "status": c, "artifact": r}))
        _store.append_event(run_dir, {"type": "stage_done" if status == "done" else "stage_start",
                                      "stage": sid, "msg": name, "ref": art})
    # a pending gate: Tech Lead plan review
    gate_id = "g-plan-review"
    _store.write_json_atomic(os.path.join(run_dir, "gates", gate_id + ".json"), {
        "id": gate_id, "run_id": RUN_ID, "kind": "approval",
        "title": "Duyệt plan Book Detail?",
        "question": "Plan đụng 8 file, thêm 1 UseCase mới (GetBookDetailUseCase). "
                    "APPROVE để Coder bắt đầu, hay REQUEST CHANGES?",
        "options": [{"id": "approve", "label": "APPROVE"},
                    {"id": "request_changes", "label": "REQUEST CHANGES"},
                    {"id": "escalate", "label": "ESCALATE PM"}],
        "allow_freeform": True,
        "context_refs": ["plans/261127-book-detail/plan.md"],
        "raised_by": "tech-lead", "raised_at": _store.now_iso(), "status": "pending",
    })
    _store.update_state(run_dir, lambda st: st.update({"gates_pending": [gate_id]}) or st)
    _store.append_event(run_dir, {"type": "gate_raised", "level": "gate",
                                  "msg": "Duyệt plan Book Detail?", "ref": gate_id})
    # sample bugs for the panel
    bugs_dir = os.path.join(project, ".harness", "run", "bugs")
    _store.write_json_atomic(os.path.join(bugs_dir, "demo.json"), {
        "fetched_at": _store.now_iso(), "jql": "DEMO",
        "bugs": [
            {"key": "DEMO-101", "title": "[Player] Nút Share chồng lên tiêu đề",
             "priority": "Medium", "status": "Open", "screen_hint": "Player",
             "actual": "Share đè tiêu đề", "expected": "Share canh phải", "url": ""},
            {"key": "DEMO-102", "title": "[Library] Crash khi kệ rỗng",
             "priority": "High", "status": "Open", "screen_hint": "Library",
             "actual": "NPE khi list rỗng", "expected": "Hiện empty state", "url": ""},
        ]})
    return run_dir, gate_id


def wait_gate(run_dir, gate_id, timeout=600):
    """Simulate the blocked worker: block on the gate, then continue when answered."""
    sys.path.insert(0, os.path.join(ROOT, "bin"))
    from gate_wait import wait_for_answer  # noqa
    print("[demo-agent] blocked on gate %s — answer it on the page…" % gate_id)
    ans = wait_for_answer(run_dir, gate_id, timeout, 1.0)
    if ans is None:
        print("[demo-agent] timed out")
        return
    print("[demo-agent] got answer: %s" % ans)
    # The server already flipped the gate to answered + dropped it from pending
    # when the page answered; here we just continue the pipeline per the choice.
    if ans.get("option_id") == "approve":
        _store.update_state(run_dir, lambda st: _store.upsert_stage(st, {
            "id": "implement", "status": "done"}))
        _store.append_event(run_dir, {"type": "stage_done", "stage": "implement",
                                      "msg": "Coder xong sau khi plan được APPROVE"})
        _store.update_state(run_dir, lambda st: _store.upsert_stage(st, {
            "id": "review", "name": "Review+QA", "agent": "reviewer", "status": "done"}))
        _store.update_state(run_dir, lambda st: st.update({"status": "done",
            "pr": {"url": "https://example/pr/999", "state": "draft"}}) or st)
        _store.append_event(run_dir, {"type": "run_done", "msg": "pipeline DONE (demo)"})
    else:
        _store.update_state(run_dir, lambda st: st.update({"status": "blocked"}) or st)
        _store.append_event(run_dir, {"type": "run_blocked",
                                      "msg": "Owner yêu cầu đổi plan: " + (ans.get("note") or "")})
    print("[demo-agent] continued; run updated.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", default=os.getcwd())
    p.add_argument("--wait", action="store_true",
                   help="after seeding, block on the gate like a real worker")
    args = p.parse_args()
    run_dir, gate_id = seed(os.path.abspath(args.project))
    print("[demo] seeded run at %s" % run_dir)
    if args.wait:
        wait_gate(run_dir, gate_id)


if __name__ == "__main__":
    main()
