import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bin"))

import _store  # noqa: E402
import emit  # noqa: E402
import raise_gate  # noqa: E402
import gate_wait  # noqa: E402
from cr import gates, runstate  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = os.path.join(self.tmp, ".harness", "run", "feature-x-1")

    def test_init_and_stage_and_status(self):
        emit.main([self.run_dir, "init", "--run-id", "feature-x-1",
                   "--kind", "feature", "--slug", "x", "--title", "X feature"])
        emit.main([self.run_dir, "stage", "--id", "plan", "--name", "Plan",
                   "--agent", "architect", "--status", "running"])
        emit.main([self.run_dir, "stage", "--id", "plan", "--status", "done",
                   "--artifact", "plans/x/plan.md"])
        emit.main([self.run_dir, "status", "--status", "done"])
        st = _store.read_json(_store.state_path(self.run_dir))
        self.assertEqual(st["status"], "done")
        self.assertEqual(len(st["stages"]), 1)
        self.assertEqual(st["stages"][0]["status"], "done")
        self.assertEqual(st["stages"][0]["artifact"], "plans/x/plan.md")

    def test_events_appended_and_read(self):
        emit.main([self.run_dir, "init", "--run-id", "feature-x-1"])
        emit.main([self.run_dir, "event", "--type", "log", "--msg", "hello"])
        emit.main([self.run_dir, "event", "--type", "log", "--msg", "world"])
        evs = runstate.read_events(self.tmp, "feature-x-1")
        msgs = [e["msg"] for e in evs if e.get("type") == "log"]
        self.assertEqual(msgs, ["hello", "world"])
        # 'after' skips already-seen lines
        later = runstate.read_events(self.tmp, "feature-x-1", after=evs[-1]["seq"] + 1)
        self.assertEqual(later, [])

    def test_emit_never_raises_on_bad_dir(self):
        # a path under a file (not creatable) must still exit 0
        bad = os.path.join(self.tmp, "afile")
        open(bad, "w").close()
        rc = emit.main([os.path.join(bad, "sub"), "event", "--msg", "x"])
        self.assertEqual(rc, 0)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run_dir = os.path.join(self.tmp, ".harness", "run", "feature-x-1")
        _store.init_state(self.run_dir, "feature-x-1", "feature", "x", "X")

    def test_raise_then_answer_roundtrip(self):
        raise_gate.main([self.run_dir, "--id", "g1", "--title", "Approve?",
                         "--question", "ok?", "--option", "approve:APPROVE",
                         "--option", "reject:REJECT", "--allow-freeform"])
        pend = runstate.pending_gates(self.tmp, "feature-x-1")
        self.assertEqual(len(pend), 1)
        self.assertEqual(pend[0]["id"], "g1")
        self.assertEqual(len(pend[0]["options"]), 2)

        # page answers
        ok, ans = gates.answer_gate(self.tmp, "feature-x-1", "g1", "approve", "go")
        self.assertTrue(ok)

        # worker's gate_wait sees the answer immediately
        got = gate_wait.wait_for_answer(self.run_dir, "g1", timeout=5, interval=0.1)
        self.assertIsNotNone(got)
        self.assertEqual(got["option_id"], "approve")
        self.assertEqual(got["note"], "go")

        # answering twice is rejected
        ok2, _ = gates.answer_gate(self.tmp, "feature-x-1", "g1", "approve")
        self.assertFalse(ok2)

    def test_gate_wait_timeout(self):
        raise_gate.main([self.run_dir, "--id", "g2", "--title", "Q"])
        got = gate_wait.wait_for_answer(self.run_dir, "g2", timeout=0.2, interval=0.05)
        self.assertIsNone(got)


class FallbackScanTest(unittest.TestCase):
    def test_scan_plan_md_status(self):
        tmp = tempfile.mkdtemp()
        d = os.path.join(tmp, "plans", "261127-1000-book-detail")
        os.makedirs(d)
        with open(os.path.join(d, "plan.md"), "w") as fh:
            fh.write("# Plan — Book Detail\n\nStatus: implemented\n")
        runs = runstate.scan_fallback_runs(tmp)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["slug"], "book-detail")
        self.assertEqual(runs[0]["status"], "done")
        self.assertEqual(runs[0]["stages"][0]["id"], "plan")


if __name__ == "__main__":
    unittest.main()
