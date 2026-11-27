"""Build and run the ``orca`` CLI commands that spawn harness workers.

Decision (owner, Phase 2): server shells the orca CLI directly (no coordinator
agent). One worktree per feature/bug (not per stage) — the harness skill chains
roles inside it. Workers report progress by calling the Control Room ``bin/``
scripts; gates go through the file contract, answered on the page.

Functions that build argv are pure and unit-tested; ``run_spawn`` executes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

CONTROL_ROOM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(CONTROL_ROOM_DIR, "bin")


def orca_bin() -> str:
    return os.environ.get("ORCA_BIN") or shutil.which("orca") or "orca"


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "task"


def run_id_for(kind: str, slug: str, ts: str) -> str:
    return "%s-%s-%s" % (kind, _slugify(slug), ts)


# --- prompt builders -------------------------------------------------------

_PROGRESS_BLOCK = """
## Control Room progress protocol (bắt buộc)
Bạn đang chạy dưới Control Room. Report tiến độ bằng các script sau (python3 stdlib, không phá pipeline nếu lỗi):
- Khởi tạo run (1 lần):
  python3 {bin}/emit.py {run_dir} init --run-id {run_id} --kind {kind} --slug "{slug}" --title "{title}"
- Mỗi stage bắt đầu/xong:
  python3 {bin}/emit.py {run_dir} stage --id <stage-id> --name "<Tên>" --agent <role> --status running|done [--artifact <path>]
- Log tùy ý:
  python3 {bin}/emit.py {run_dir} event --type log --stage <id> --msg "<câu ngắn>"
- Mở PR xong:
  python3 {bin}/emit.py {run_dir} pr --url <PR_URL> --state draft|ready
- Kết thúc:
  python3 {bin}/emit.py {run_dir} status --status done|blocked|failed

## Gate — thay vì hỏi trong chat
Khi cần owner quyết (approval plan, ambiguity, scope guard, blocker), ĐỪNG hỏi trong chat. Làm:
  GID=$(python3 {bin}/raise_gate.py {run_dir} --id <gate-id> --kind approval \\
        --title "<câu hỏi ngắn>" --question "<chi tiết>" \\
        --option approve:APPROVE --option request_changes:"REQUEST CHANGES" --allow-freeform \\
        [--context-ref <path>])
  ANS=$(python3 {bin}/gate_wait.py {run_dir} $GID --timeout 7200)
Rồi đọc $ANS (JSON: option_id + note) và tiếp tục đúng theo lựa chọn của owner. Nếu gate_wait timeout (exit 2) mới fallback hỏi chat.
"""


def _progress_block(run_dir, run_id, kind, slug, title):
    return _PROGRESS_BLOCK.format(bin=BIN_DIR, run_dir=run_dir, run_id=run_id,
                                  kind=kind, slug=slug, title=title)


def feature_prompt(run_dir, run_id, slug, title, description):
    return (
        "Bạn là worker của harness chạy pipeline FEATURE (1 feature = worktree này; "
        "chain role Architect → Coder → Reviewer/QA bên trong, đừng tách mỗi stage 1 worktree).\n"
        "Invoke skill `/feature` cho feature sau:\n"
        "- Slug: %s\n- Mô tả: %s\n\n"
        "Theo đúng `skills/feature/references/single.md`. Mở PR draft cuối pipeline.\n"
        "%s" % (slug, description, _progress_block(run_dir, run_id, "feature", slug, title))
    )


def bugfix_prompt(run_dir, run_id, keys, mode, bugs_file):
    return (
        "Bạn là worker fix bug của harness. Invoke skill `/bug-fix` mode `%s` cho bug: %s.\n"
        "Nội dung bug lấy từ file JSON (đã fetch sẵn từ Jira): %s (đọc bằng key, field "
        "title/actual/expected/url). Fix đúng root cause theo `agents/bug-fixer.md`, mở PR draft, "
        "qua `bug-reviewer` trước khi ready.\n"
        "%s" % (mode, ", ".join(keys), bugs_file,
                _progress_block(run_dir, run_id, "bugfix", keys[0] if keys else mode,
                                ("Fix " + ", ".join(keys))))
    )


def jira_fetch_prompt(bugs_out, project_key, jql):
    jql = jql or ("project = %s AND issuetype = Bug AND statusCategory != Done" % project_key)
    return (
        "Dùng Jira MCP (jira_search) đọc bug cho Bug panel. KHÔNG hardcode/commit token.\n"
        "JQL: %s\n"
        "Gọi jira_search(jql, fields=\"summary,description,status,priority,labels,"
        "components,issuetype\", limit=50). Normalize theo "
        "`skills/bug-fix/references/intake-and-context.md` §1 (tách actual/expected, screen_hint "
        "từ tiền tố [..] của title). KHÔNG chép email/tên reporter.\n"
        "Ghi ra file JSON: %s với shape {\"fetched_at\":..., \"jql\":..., \"bugs\":[{\"key\",\"title\","
        "\"priority\",\"status\",\"screen_hint\",\"actual\",\"expected\",\"url\"}]}.\n"
        "Chỉ ghi file đó rồi dừng; không sửa code." % (jql, bugs_out)
    )


# --- argv builders ---------------------------------------------------------

def worktree_create_argv(name, agent, prompt, parent="active"):
    return [orca_bin(), "worktree", "create", "--name", name,
            "--parent-worktree", parent, "--agent", agent,
            "--prompt", prompt, "--json"]


def run_spawn(argv, cwd):
    """Execute an orca spawn command. Returns (ok, parsed_json_or_text)."""
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"error": str(exc)}
    out = proc.stdout.strip()
    if proc.returncode != 0:
        return False, {"error": proc.stderr.strip() or out or "orca failed",
                       "returncode": proc.returncode}
    try:
        return True, json.loads(out)
    except ValueError:
        return True, {"raw": out}
