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
    """Ask the questions. Returns the chosen state; saving is the caller's job."""

    machine = _ask(
        questionary.text(
            "Name this machine",
            default=current.machine if current else default_machine_name(runner),
            style=_STYLE,
        )
    ).strip()

    profile_choices = [
        Choice(
            title=f"{name:<10} {'everything' if entries == ['*'] else f'{len(entries)} modules'}",
            value=name,
        )
        for name, entries in catalog.profiles.items()
    ]
    profile_choices.append(Choice(title="custom     pick modules yourself", value=CUSTOM))

    profile = _ask(
        questionary.select(
            "Profile",
            choices=profile_choices,
            default=next(
                (c for c in profile_choices if c.value == (current.profile if current else "work")),
                None,
            ),
            style=_STYLE,
        )
    )

    # Pre-tick from the current machine if reconfiguring, otherwise the profile.
    # An empty saved selection falls through to the profile on purpose: pre-ticking
    # nothing makes plain Enter save nothing, so an empty machine.toml would
    # otherwise re-empty itself every time the wizard runs.
    if current and current.modules and profile == current.profile:
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

    chosen = _ask(
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
    resolved = catalog.resolve(only=chosen)
    pulled = [m.id for m in resolved if m.id not in chosen and not m.always]
    if pulled:
        questionary.print(f"  + required by your selection: {', '.join(pulled)}", style="fg:yellow")

    selected_ids = [m.id for m in resolved if not m.always]

    picks: dict[str, list[str]] = {}
    for module in resolved:
        if module.select != "pick":
            continue
        if current and module.id in current.picks:
            checked = set(current.picks[module.id])
        else:
            checked = set(module.default)
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
        picks[module.id] = list(answer)

    return MachineState(
        machine=machine,
        profile=profile,
        modules=selected_ids,
        picks=picks,
        vars=dict(current.vars) if current else {},
    )
