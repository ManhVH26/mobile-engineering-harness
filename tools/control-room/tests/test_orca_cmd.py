import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cr import orca  # noqa: E402


class OrcaCmdTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(orca._slugify("Book Detail Screen!"), "book-detail-screen")
        self.assertEqual(orca._slugify(""), "task")

    def test_run_id(self):
        self.assertEqual(orca.run_id_for("feature", "Book Detail", "261127-1000"),
                         "feature-book-detail-261127-1000")

    def test_worktree_create_argv_shape(self):
        argv = orca.worktree_create_argv("cr-feat-x", "claude", "hello", parent="active")
        self.assertIn("worktree", argv)
        self.assertIn("create", argv)
        self.assertEqual(argv[argv.index("--name") + 1], "cr-feat-x")
        self.assertEqual(argv[argv.index("--agent") + 1], "claude")
        self.assertEqual(argv[argv.index("--prompt") + 1], "hello")
        self.assertEqual(argv[argv.index("--parent-worktree") + 1], "active")
        self.assertIn("--json", argv)

    def test_feature_prompt_has_progress_and_gate_protocol(self):
        rid = "feature-x-1"
        rd = "/tmp/proj/.harness/run/" + rid
        pr = orca.feature_prompt(rd, rid, "x", "X", "build X")
        self.assertIn("/feature", pr)
        self.assertIn("emit.py", pr)
        self.assertIn("raise_gate.py", pr)
        self.assertIn("gate_wait.py", pr)
        self.assertIn(rd, pr)

    def test_bugfix_prompt(self):
        pr = orca.bugfix_prompt("/tmp/rd", "bugfix-1", ["ABC-1"], "note", "/tmp/bugs.json")
        self.assertIn("/bug-fix", pr)
        self.assertIn("note", pr)
        self.assertIn("ABC-1", pr)

    def test_jira_prompt_no_hardcoded_token(self):
        pr = orca.jira_fetch_prompt("/tmp/bugs.json", "ABC", "")
        self.assertIn("jira_search", pr)
        self.assertIn("project = ABC", pr)
        self.assertNotIn("token", pr.lower().split("hardcode")[0])  # no token literal before the warning


if __name__ == "__main__":
    unittest.main()
