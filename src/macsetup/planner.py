"""Turn a module selection plus machine state into a reviewable plan.

Nothing here mutates anything. `plan` and `apply` share this code so the
preview is always exactly what apply will act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import files as files_mod
from .detect import System, installed_name
from .manifest import FileSpec, Module, Package


@dataclass(frozen=True)
class FileAction:
    spec: FileSpec
    outcome: files_mod.Outcome

    @property
    def pending(self) -> bool:
        return self.outcome.pending


@dataclass(frozen=True)
class ModulePlan:
    module: Module
    missing: list[Package] = field(default_factory=list)
    satisfied: list[Package] = field(default_factory=list)
    skipped: list[Package] = field(default_factory=list)
    file_actions: list[FileAction] = field(default_factory=list)

    @property
    def pending_files(self) -> list[FileAction]:
        return [a for a in self.file_actions if a.pending]

    @property
    def pending(self) -> bool:
        return bool(self.missing) or bool(self.pending_files)

    @property
    def selected(self) -> list[Package]:
        return [*self.missing, *self.satisfied]


@dataclass(frozen=True)
class Plan:
    modules: list[ModulePlan] = field(default_factory=list)

    @property
    def pending(self) -> list[ModulePlan]:
        return [m for m in self.modules if m.pending]

    @property
    def missing_count(self) -> int:
        return sum(len(m.missing) for m in self.modules)

    @property
    def satisfied_count(self) -> int:
        return sum(len(m.satisfied) for m in self.modules)

    @property
    def file_change_count(self) -> int:
        return sum(len(m.pending_files) for m in self.modules)

    @property
    def converged(self) -> bool:
        return self.missing_count == 0 and self.file_change_count == 0

    def selected_packages(self) -> list[Package]:
        return [p for m in self.modules for p in m.selected]


def _file_action(spec: FileSpec, root: Path, variables: dict[str, str]) -> FileAction:
    source = root / spec.source
    dest = files_mod.expand(spec.target)

    if spec.kind == "copy":
        outcome = files_mod.plan_copy(source, dest)
    elif spec.kind == "render":
        outcome = files_mod.plan_render(source, dest, variables)
    else:
        outcome = files_mod.plan_block(
            dest,
            source.read_text(encoding="utf-8"),
            comment=spec.comment,
            position=spec.position,
        )
    return FileAction(spec=spec, outcome=outcome)


def build_plan(
    modules: list[Module],
    system: System,
    picks: dict[str, set[str]] | None = None,
    *,
    files_root: Path | None = None,
    variables: dict[str, str] | None = None,
) -> Plan:
    picks = picks or {}
    variables = variables or {}
    plans: list[ModulePlan] = []

    for module in modules:
        chosen = module.selected_packages(picks.get(module.id))
        chosen_names = {p.name for p in chosen}
        missing = [p for p in chosen if not system.has(p.name, cask=p.cask)]
        satisfied = [p for p in chosen if system.has(p.name, cask=p.cask)]
        skipped = [p for p in module.packages if p.name not in chosen_names]

        actions: list[FileAction] = []
        if module.files and files_root is not None:
            actions = [_file_action(spec, files_root, variables) for spec in module.files]

        plans.append(
            ModulePlan(
                module=module,
                missing=missing,
                satisfied=satisfied,
                skipped=skipped,
                file_actions=actions,
            )
        )

    return Plan(modules=plans)


def untracked(plan: Plan, system: System) -> tuple[list[str], list[str]]:
    """Installed packages that no selected module accounts for.

    Informational in Phase 1 -- this is what `macsetup prune` will eventually
    offer to remove.
    """
    known_formulae = {
        installed_name(p.name) for p in plan.selected_packages() if not p.cask and p.mas is None
    }
    known_casks = {installed_name(p.name) for p in plan.selected_packages() if p.cask}
    return (
        sorted(system.formulae - known_formulae),
        sorted(system.casks - known_casks),
    )
