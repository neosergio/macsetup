"""Machine inspection.

The whole point of this module is that `brew list` runs exactly twice per
invocation, no matter how many packages the catalog holds. Checking 60 packages
must not mean 60 subprocess calls.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field

from .runner import Runner


@dataclass(frozen=True)
class System:
    arch: str
    macos: str
    brew: bool
    formulae: frozenset[str] = field(default_factory=frozenset)
    casks: frozenset[str] = field(default_factory=frozenset)

    def has(self, name: str, *, cask: bool) -> bool:
        return name in (self.casks if cask else self.formulae)

    @property
    def installed_count(self) -> int:
        return len(self.formulae) + len(self.casks)


def detect(runner: Runner) -> System:
    brew_present = runner.run(["command", "-v", "brew"]).ok or _brew_responds(runner)

    formulae: frozenset[str] = frozenset()
    casks: frozenset[str] = frozenset()
    if brew_present:
        formulae = frozenset(runner.run(["brew", "list", "--formula", "-1"]).lines())
        casks = frozenset(runner.run(["brew", "list", "--cask", "-1"]).lines())

    return System(
        arch=platform.machine(),
        macos=platform.mac_ver()[0] or "unknown",
        brew=brew_present,
        formulae=formulae,
        casks=casks,
    )


def _brew_responds(runner: Runner) -> bool:
    # `command -v` is a shell builtin and will not exist as an executable, so
    # fall back to asking brew directly.
    return runner.run(["brew", "--prefix"]).ok
