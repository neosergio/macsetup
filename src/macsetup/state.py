"""Per-machine state.

Lives outside the repo, in ~/.config/macsetup/machine.toml. Identical manifests
in git plus a small local override file is what makes 5 machines tractable.

The module list is stored explicitly rather than derived from the profile name.
A module added to a profile upstream must not silently install itself on five
machines the next time they sync -- `macsetup configure` adopts it deliberately.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from .manifest import catalog_vars


def config_dir() -> Path:
    override = os.environ.get("MACSETUP_CONFIG")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "macsetup"


def state_path() -> Path:
    return config_dir() / "machine.toml"


def builtin_vars(machine: str) -> dict[str, str]:
    """Variables every render gets, with or without a machine.toml.

    Defaults come from the catalog's vars.yaml, not from this package: the
    engine has no opinion about who you are. On top of those, two are always
    supplied here --

    `machine`  the machine name, so one template can branch per machine
    `home`     an absolute path, for config values whose reader does not
               tilde-expand. git expands ~ in core.hooksPath; a GUI client
               carrying its own git implementation may not.
    """
    return {**catalog_vars(), "machine": machine, "home": str(Path.home())}


@dataclass
class MachineState:
    machine: str
    profile: str
    modules: list[str] = field(default_factory=list)
    picks: dict[str, list[str]] = field(default_factory=dict)
    vars: dict[str, str] = field(default_factory=dict)

    def template_vars(self) -> dict[str, str]:
        return {**builtin_vars(self.machine), **self.vars}

    def picks_as_sets(self) -> dict[str, set[str]]:
        return {module_id: set(names) for module_id, names in self.picks.items()}

    def to_toml(self) -> dict[str, Any]:
        doc: dict[str, Any] = {
            "machine": self.machine,
            "profile": self.profile,
            "modules": list(self.modules),
        }
        if self.picks:
            doc["picks"] = {k: sorted(v) for k, v in self.picks.items() if v}
        if self.vars:
            doc["vars"] = dict(self.vars)
        return doc


def load(path: Path | None = None) -> MachineState | None:
    path = path or state_path()
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        doc = tomllib.load(handle)
    return MachineState(
        machine=doc.get("machine", "unknown"),
        profile=doc.get("profile", "custom"),
        modules=list(doc.get("modules", [])),
        picks={k: list(v) for k, v in (doc.get("picks") or {}).items()},
        vars=dict(doc.get("vars") or {}),
    )


def save(state: MachineState, path: Path | None = None) -> Path:
    path = path or state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# macsetup machine state -- written by `macsetup init` / `configure`.\n"
        "# Safe to edit by hand; `modules` is the authoritative selection.\n\n"
    )
    path.write_text(header + tomli_w.dumps(state.to_toml()), encoding="utf-8")
    return path
