#!/usr/bin/env python3
"""Control Room entrypoint.

    python3 run.py [--project <path>] [--port N] [--no-open] [--jira-project KEY]

Default: project = current directory, auto-pick a free port, auto-open browser.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cr import server  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Control Room — control surface over the harness.")
    p.add_argument("--project", default=os.getcwd(),
                   help="project repo root to watch (default: cwd)")
    p.add_argument("--port", type=int, default=0, help="0 = auto free port (default)")
    p.add_argument("--no-open", action="store_true", help="don't auto-open the browser")
    p.add_argument("--jira-project", default=os.environ.get("CONTROL_ROOM_JIRA_PROJECT", ""),
                   help="default Jira project key for the Bug panel")
    args = p.parse_args(argv)
    project = os.path.abspath(args.project)
    if not os.path.isdir(project):
        p.error("project not a directory: %s" % project)
    server.serve(project, port=args.port, open_browser=not args.no_open,
                 jira_project=args.jira_project)


if __name__ == "__main__":
    main()
