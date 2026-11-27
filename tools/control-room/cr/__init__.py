"""Control Room — a local HTML control surface over the Orca-driven harness.

Standalone tooling. Reads the harness project's state files and shells the
``orca`` CLI; it never imports harness skills/constitution, and the harness
runs unchanged whether or not the Control Room is present.
"""
__version__ = "0.1.0"
