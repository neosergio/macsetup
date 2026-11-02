"""Upgrading macsetup itself.

install.sh puts macsetup on PATH with `uv tool install`, so uv owns the
install and upgrading it is `uv tool upgrade`. The refresh matters right after
a release: uv caches PyPI's index, and without it a version published minutes
ago can come back as "Nothing to upgrade".
"""

from __future__ import annotations

from .runner import Result, Runner

COMMAND = ["uv", "tool", "upgrade", "--refresh-package", "macsetup", "macsetup"]


def upgrade(runner: Runner) -> Result:
    # Streamed, not captured: uv's own "Updated macsetup v0.2.4 -> v0.2.5"
    # line is the report.
    return runner.run(COMMAND, capture=False)
