"""The interactive selection flow.

Only ever *decides* things -- it returns a MachineState and touches nothing
else. Installing is apply's job, planning is planner's. Keeping the wizard
free of side effects is what lets every answer also be expressible as a flag.
"""

from __future__ import annotations

import socket

import questionary
from questionary import Choice

from .detect import System
from .manifest import Catalog, Module
from .runner import Runner
from .state import MachineState

CUSTOM = "custom"
# Sentinels for navigation answers. Not valid module, profile or package names
# by construction (they contain characters the catalog never uses).
BACK = "<back>"
SAVE = "<save>"

_STYLE = questionary.Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:cyan"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("instruction", "fg:#888888"),
    ]
)


class WizardAborted(RuntimeError):
    pass


def _ask(question):
    answer = question.ask()
    if answer is None:
        raise WizardAborted("cancelled")
    return answer


def default_machine_name(runner: Runner) -> str:
    result = runner.run(["scutil", "--get", "ComputerName"])
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    return socket.gethostname().removesuffix(".local")


def _module_label(module: Module, system: System) -> str:
    total = len(module.packages)
    installed = sum(1 for p in module.packages if system.has(p.name, cask=p.cask))
    suffix = f"{installed}/{total} installed" if installed else f"{total} pkg"
    detail = f" — {module.description}" if module.description else ""
    return f"{module.id:<14} [{suffix}]{detail}"


def run(
    catalog: Catalog,
    system: System,
    runner: Runner,
    *,
    current: MachineState | None = None,
) -> MachineState:
    """Ask the questions. Returns the chosen state; saving is the caller's job.

    A sequence of steps rather than straight-line prompts, so any answer can be
    revisited: the profile menu has a Back entry, and a review screen at the
    end jumps to any earlier step with the answers given so far pre-filled.
    """
    machine = current.machine if current else default_machine_name(runner)
    profile = current.profile if current else "work"
    # None until the module step has been answered; going back keeps the answer.
    chosen: list[str] | None = None
    picks: dict[str, list[str]] = dict(current.picks) if current else {}

    step = "name"
    only_pick: str | None = None  # set when review asks to redo one module's picks
    while True:
        if step == "name":
            machine = _ask(questionary.text("Name this machine", default=machine, style=_STYLE))
            machine = machine.strip()
            step = "profile"

        elif step == "profile":
            answer = _ask_profile(catalog, profile)
            if answer == BACK:
                step = "name"
                continue
            if answer != profile:
                chosen = None  # a different profile means different pre-ticks
            profile = answer
            step = "modules"

        elif step == "modules":
            chosen = _ask_modules(catalog, system, current, profile, chosen)
            step = "picks"

        elif step == "picks":
            for module in catalog.resolve(only=chosen):
                if module.select != "pick" or (only_pick and module.id != only_pick):
                    continue
                picks[module.id] = _ask_picks(module, system, picks.get(module.id))
            only_pick = None
            step = "review"

        elif step == "review":
            resolved = catalog.resolve(only=chosen)
            action = _review(machine, profile, resolved, picks)
            if action == SAVE:
                break
            if action.startswith("pick:"):
                only_pick = action.removeprefix("pick:")
                step = "picks"
            else:
                step = action

    resolved = catalog.resolve(only=chosen)
    return MachineState(
        machine=machine,
        profile=profile,
        modules=[m.id for m in resolved if not m.always],
        picks={m.id: picks[m.id] for m in resolved if m.select == "pick" and m.id in picks},
        vars=dict(current.vars) if current else {},
    )


def _ask_profile(catalog: Catalog, profile: str) -> str:
    choices = [
        Choice(
            title=f"{name:<10} {'everything' if entries == ['*'] else f'{len(entries)} modules'}",
            value=name,
        )
        for name, entries in catalog.profiles.items()
    ]
    choices.append(Choice(title="custom     pick modules yourself", value=CUSTOM))
    choices.append(Choice(title="← back", value=BACK))
    return _ask(
        questionary.select(
            "Profile",
            choices=choices,
            default=next((c for c in choices if c.value == profile), None),
            style=_STYLE,
        )
    )


def _ask_modules(
    catalog: Catalog,
    system: System,
    current: MachineState | None,
    profile: str,
    chosen: list[str] | None,
) -> list[str]:
    # A previous answer to this step wins; then the current machine if
    # reconfiguring the same profile; otherwise the profile itself. An empty
    # saved selection falls through to the profile on purpose: pre-ticking
    # nothing makes plain Enter save nothing, so an empty machine.toml would
    # otherwise re-empty itself every time the wizard runs.
    if chosen is not None:
        preselected = set(chosen)
    elif current and current.modules and profile == current.profile:
        preselected = set(current.modules)
    elif profile == CUSTOM:
        preselected = set()
    else:
        preselected = {m.id for m in catalog.resolve(profile) if not m.always}

    optional = [m for m in catalog.modules.values() if not m.always]
    always = [m for m in catalog.modules.values() if m.always]
    if always:
        names = ", ".join(m.id for m in always)
        questionary.print(f"  always included: {names}", style="fg:#888888")

    answer = _ask(
        questionary.checkbox(
            "Modules for this machine",
            choices=[
                Choice(
                    title=_module_label(m, system),
                    value=m.id,
                    checked=m.id in preselected,
                )
                for m in optional
            ],
            style=_STYLE,
        )
    )

    # requires may pull in modules the user did not tick; surface that rather
    # than silently installing something they did not choose.
    pulled = [m.id for m in catalog.resolve(only=answer) if m.id not in answer and not m.always]
    if pulled:
        questionary.print(f"  + required by your selection: {', '.join(pulled)}", style="fg:yellow")
    return list(answer)


def _ask_picks(module: Module, system: System, previous: list[str] | None) -> list[str]:
    checked = set(previous) if previous is not None else set(module.default)
    choices = []
    for package in module.packages:
        mark = "  (installed)" if system.has(package.name, cask=package.cask) else ""
        choices.append(
            Choice(
                title=f"{package.name}{mark}",
                value=package.name,
                checked=package.name in checked,
            )
        )
    answer = _ask(
        questionary.checkbox(f"{module.name} — choose packages", choices=choices, style=_STYLE)
    )
    return list(answer)


def _review(machine: str, profile: str, resolved: list[Module], picks: dict[str, list[str]]) -> str:
    """Summarise the answers and ask whether to save or go back to a step."""
    modules = [m for m in resolved if not m.always]
    questionary.print(f"\n  machine  {machine}", style="bold")
    questionary.print(f"  profile  {profile}", style="bold")
    questionary.print(f"  modules  {', '.join(m.id for m in modules) or '(none)'}", style="bold")
    pick_modules = [m for m in modules if m.select == "pick"]
    for m in pick_modules:
        questionary.print(f"    {m.id:<12} {', '.join(picks.get(m.id, [])) or '(none)'}")

    choices = [
        Choice(title="Save", value=SAVE),
        Choice(title="← change machine name", value="name"),
        Choice(title="← change profile", value="profile"),
        Choice(title="← change modules", value="modules"),
    ]
    choices += [Choice(title=f"← change {m.name}", value=f"pick:{m.id}") for m in pick_modules]
    return _ask(questionary.select("Review", choices=choices, style=_STYLE))
