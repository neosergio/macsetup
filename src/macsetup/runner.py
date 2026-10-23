"""The subprocess seam.

Every external command goes through a Runner. Production uses SubprocessRunner;
tests inject FakeRunner so planner logic can be exercised without touching the
machine running the tests.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Result:
    code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0

    def lines(self) -> list[str]:
        return [line for line in self.stdout.splitlines() if line.strip()]


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], result: Result) -> None:
        self.cmd = list(cmd)
        self.result = result
        super().__init__(f"`{' '.join(cmd)}` exited {result.code}: {result.stderr.strip()}")


class Runner(Protocol):
    def run(self, cmd: Sequence[str], *, capture: bool = True, check: bool = False) -> Result: ...


class SubprocessRunner:
    """Runs commands for real.

    capture=False streams straight to the terminal, which is what we want for
    `brew bundle install` -- Homebrew's own progress output is better than
    anything we would reconstruct from captured text.
    """

    def run(self, cmd: Sequence[str], *, capture: bool = True, check: bool = False) -> Result:
        proc = subprocess.run(list(cmd), capture_output=capture, text=True)
        result = Result(proc.returncode, proc.stdout or "", proc.stderr or "")
        if check and not result.ok:
            raise CommandError(cmd, result)
        return result


@dataclass
class FakeRunner:
    """Test double. Maps a joined command string to a canned Result."""

    responses: dict[str, Result] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    default: Result = Result(0)

    def run(self, cmd: Sequence[str], *, capture: bool = True, check: bool = False) -> Result:
        cmd = list(cmd)
        self.calls.append(cmd)
        result = self.responses.get(" ".join(cmd), self.default)
        if check and not result.ok:
            raise CommandError(cmd, result)
        return result
