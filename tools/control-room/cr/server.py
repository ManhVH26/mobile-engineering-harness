"""Control Room HTTP server — python3 stdlib only.

Binds 127.0.0.1 (localhost only). Serves one page per project and a small JSON
API; streams events over SSE; shells the ``orca`` CLI to spawn harness workers.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bin"))

from cr import runstate, orca, gates  # noqa: E402
import _store  # noqa: E402

WEB_DIR = os.path.join(ROOT, "web")
_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_SAIGON = datetime.timezone(datetime.timedelta(hours=7))


def _ts() -> str:
    return datetime.datetime.now(_SAIGON).strftime("%y%m%d-%H%M%S")


def _safe_id(value: str) -> bool:
    return bool(value) and bool(_ID_RE.match(value)) and ".." not in value


class Handler(BaseHTTPRequestHandler):
    server_version = "ControlRoom/0.1"

    # bound at serve() time
    project = os.getcwd()
    default_jira_project = ""

    def log_message(self, fmt, *args):  # quieter log
        sys.stderr.write("[cr] %s - %s\n" % (self.address_string(), fmt % args))

    # --- helpers ---
    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, ctype):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    # --- routing ---
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p == "/" or p == "/index.html":
            return self._send_file(os.path.join(WEB_DIR, "index.html"),
                                   "text/html; charset=utf-8")
        if p == "/api/config":
            return self._send_json({
                "project": self.project,
                "project_name": os.path.basename(self.project.rstrip("/")),
                "has_orca": bool(orca.orca_bin()),
                "default_jira_project": self.default_jira_project,
            })
        if p == "/api/runs":
            return self._send_json({"runs": runstate.list_runs(self.project)})
        if p == "/api/run":
            rid = (q.get("run") or [""])[0]
            if not _safe_id(rid):
                return self._send_json({"error": "bad run id"}, 400)
            run = runstate.get_run(self.project, rid)
            return self._send_json(run or {"error": "not found"},
                                   200 if run else 404)
        if p == "/api/gates":
            rid = (q.get("run") or [""])[0]
            if not _safe_id(rid):
                return self._send_json({"error": "bad run id"}, 400)
            return self._send_json({"gates": runstate.pending_gates(self.project, rid)})
        if p == "/api/bugs":
            return self._send_json({"bugs": runstate.read_bugs(self.project)})
        if p == "/api/events":
            return self._stream_events(q)
        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        body = self._read_body()
        if p == "/api/gate/answer":
            return self._answer_gate(body)
        if p == "/api/build":
            return self._spawn_build(body)
        if p == "/api/bugs/refresh":
            return self._refresh_bugs(body)
        if p == "/api/bugs/fix":
            return self._fix_bugs(body)
        self.send_error(404)

    # --- SSE ---
    def _stream_events(self, q):
        rid = (q.get("run") or [""])[0]
        after = int((q.get("after") or ["0"])[0])
        if not _safe_id(rid):
            return self._send_json({"error": "bad run id"}, 400)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        sent = after
        idle = 0
        try:
            while True:
                evs = runstate.read_events(self.project, rid, sent)
                for ev in evs:
                    sent = ev["seq"] + 1
                    self.wfile.write(("data: %s\n\n" % json.dumps(ev, ensure_ascii=False)).encode("utf-8"))
                    self.wfile.flush()
                # also push a lightweight state tick so the page can refresh cards
                idle += 1
                if not evs and idle % 5 == 0:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            return

    # --- actions ---
    def _answer_gate(self, body):
        rid = body.get("run")
        gid = body.get("gate_id")
        if not (_safe_id(rid or "") and _safe_id(gid or "")):
            return self._send_json({"error": "bad run/gate id"}, 400)
        ok, result = gates.answer_gate(self.project, rid, gid,
                                       body.get("option_id") or "ok",
                                       body.get("note") or "")
        return self._send_json({"ok": ok, "result": result}, 200 if ok else 409)

    def _spawn_build(self, body):
        desc = (body.get("description") or "").strip()
        slug = (body.get("slug") or "").strip() or orca._slugify(desc)
        if not desc:
            return self._send_json({"error": "description required"}, 400)
        rid = orca.run_id_for("feature", slug, _ts())
        run_dir = os.path.join(self.project, ".harness", "run", rid)
        title = desc[:80]
        _store.init_state(run_dir, rid, "feature", slug, title)
        _store.append_event(run_dir, {"type": "run_start", "level": "info",
                                      "msg": "Control Room: build requested"})
        prompt = orca.feature_prompt(run_dir, rid, slug, title, desc)
        argv = orca.worktree_create_argv("cr-feat-" + slug, _agent(), prompt)
        ok, result = orca.run_spawn(argv, self.project)
        _store.append_event(run_dir, {
            "type": "worker_spawn" if ok else "error", "level": "info" if ok else "error",
            "msg": "spawned feature worker" if ok else ("spawn failed: %s" % result.get("error"))})
        return self._send_json({"ok": ok, "run_id": rid, "result": result},
                               200 if ok else 502)

    def _refresh_bugs(self, body):
        pk = (body.get("project_key") or self.default_jira_project or "").strip()
        jql = (body.get("jql") or "").strip()
        if not pk and not jql:
            return self._send_json({"error": "project_key or jql required"}, 400)
        bugs_dir = os.path.join(self.project, ".harness", "run", "bugs")
        os.makedirs(bugs_dir, exist_ok=True)
        out = os.path.join(bugs_dir, (orca._slugify(pk or "bugs")) + ".json")
        prompt = orca.jira_fetch_prompt(out, pk, jql)
        argv = orca.worktree_create_argv("cr-jira-" + orca._slugify(pk or "fetch"),
                                         _agent(), prompt)
        ok, result = orca.run_spawn(argv, self.project)
        return self._send_json({"ok": ok, "out": out, "result": result},
                               200 if ok else 502)

    def _fix_bugs(self, body):
        keys = body.get("keys") or []
        if isinstance(keys, str):
            keys = [keys]
        keys = [k for k in keys if k]
        if not keys:
            return self._send_json({"error": "keys required"}, 400)
        mode = body.get("mode") or ("batch" if len(keys) > 1 else "note")
        rid = orca.run_id_for("bugfix", keys[0], _ts())
        run_dir = os.path.join(self.project, ".harness", "run", rid)
        _store.init_state(run_dir, rid, "bugfix", keys[0], "Fix " + ", ".join(keys))
        bugs_file = os.path.join(self.project, ".harness", "run", "bugs",
                                 orca._slugify(self.default_jira_project or "bugs") + ".json")
        prompt = orca.bugfix_prompt(run_dir, rid, keys, mode, bugs_file)
        argv = orca.worktree_create_argv("cr-fix-" + orca._slugify(keys[0]), _agent(), prompt)
        ok, result = orca.run_spawn(argv, self.project)
        _store.append_event(run_dir, {
            "type": "worker_spawn" if ok else "error",
            "level": "info" if ok else "error",
            "msg": ("spawned bug-fix %s" % mode) if ok else ("spawn failed: %s" % result.get("error"))})
        return self._send_json({"ok": ok, "run_id": rid, "mode": mode, "result": result},
                               200 if ok else 502)


def _agent():
    return os.environ.get("CONTROL_ROOM_AGENT", "claude")


def serve(project, port=0, open_browser=True, jira_project=""):
    Handler.project = os.path.abspath(project)
    Handler.default_jira_project = jira_project
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    actual_port = httpd.server_address[1]
    url = "http://127.0.0.1:%d/" % actual_port
    # advertise the port so `orca ports` / other tools can find it
    try:
        run_root = os.path.join(Handler.project, ".harness", "run")
        os.makedirs(run_root, exist_ok=True)
        with open(os.path.join(run_root, "control-room.port"), "w") as fh:
            fh.write(str(actual_port) + "\n")
    except OSError:
        pass
    sys.stderr.write("[cr] Control Room cho %s\n[cr] %s\n" % (Handler.project, url))
    if open_browser:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n[cr] dừng\n")
    finally:
        httpd.server_close()
    return url
