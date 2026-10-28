"""The interactive selection flow.

Only ever *decides* things -- it returns a MachineState and touches nothing
else. Installing is apply's job, planning is planner's. Keeping the wizard
free of side effects is what lets every answer also be expressible as a flag.

People choose apps, not modules. Modules are how the catalog is organised, so
the wizard flattens them into one list: a `select: pick` module becomes a
group of apps that tick individually, and an atomic module is one line under
"Tools". Profiles are presented as what they are -- a starting point that
pre-ticks that list -- and are only asked about on a machine's first run.
"""

from __future__ import annotations

import socket

import questionary
from questionary import Choice

from . import i18n
from .detect import System
from .manifest import Catalog, Module
from .prompts import Row, toggle_list
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

# A ticked row is ("mod", module_id) for an atomic module, or
# ("pkg", module_id, package_name) for one app of a pick module.
Tick = tuple[str, ...]


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


def module_contents(module: Module, system: System | None = None) -> str:
    """What a module actually installs, for `macsetup modules`."""
    names = [
        f"{p.name} (installed)" if system and system.has(p.name, cask=p.cask) else p.name
        for p in module.packages
    ]
    if names:
        return ", ".join(names)
    if module.files:
        return f"no packages; manages {len(module.files)} file(s)"
    return "nothing"


def run(
    catalog: Catalog,
    system: System,
    runner: Runner,
    *,
    current: MachineState | None = None,
    lang: str = "en",
) -> MachineState:
    """Ask the questions. Returns the chosen state; saving is the caller's job.

    A sequence of steps rather than straight-line prompts, so any answer can be
    revisited from the review screen at the end, with what was ticked kept.
    """
    t = i18n.messages(lang)
    # A configured machine already has a selection; asking what it is for
    # would only offer to throw that away. The review screen still can.
    from_machine = bool(current and current.modules)
    machine = current.machine if current else default_machine_name(runner)
    profile = current.profile if current else _default_profile(catalog)
    ticks: set[Tick] | None = None  # None until the apps step has been answered

    step = "name"
    while True:
        if step == "name":
            machine = _ask(questionary.text(t["name"], default=machine, style=_STYLE)).strip()
            if ticks is not None:
                step = "review"  # renamed from the review screen
            else:
                step = "apps" if from_machine else "profile"

        elif step == "profile":
            answer = _ask_profile(catalog, profile, t)
            if answer == BACK:
                step = "name"
                continue
            if answer != profile or from_machine or ticks is None:
                ticks = initial_ticks(catalog, None, answer)
            # From here on the chosen starting point pre-ticks, not the machine.
            from_machine = False
            profile = answer
            step = "apps"

        elif step == "apps":
            if ticks is None:
                ticks = initial_ticks(catalog, current if from_machine else None, profile)
            ticks = _ask_apps(catalog, system, ticks, t)
            step = "review"

        elif step == "review":
            action = _review(catalog, machine, ticks or set(), t)
            if action == SAVE:
                break
            step = action

    modules, picks = selection(catalog, ticks or set())
    return MachineState(
        machine=machine,
        profile=profile,
        modules=modules,
        picks=picks,
        vars=dict(current.vars) if current else {},
    )


def _default_profile(catalog: Catalog) -> str:
    return "work" if "work" in catalog.profiles else next(iter(catalog.profiles), CUSTOM)


def initial_ticks(catalog: Catalog, current: MachineState | None, profile: str) -> set[Tick]:
    """What the apps list starts with: this machine's choices, or the profile's.

    An empty saved selection falls through to the profile on purpose: pre-ticking
    nothing makes "Done" save nothing, so an empty machine.toml would otherwise
    re-empty itself every time the wizard runs.
    """
    if current and current.modules:
        modules = [catalog.modules[m] for m in current.modules if m in catalog.modules]
        picks = current.picks
    elif profile == CUSTOM:
        return set()
    else:
        modules = [m for m in catalog.resolve(profile) if not m.always]
        picks = {}

    ticks: set[Tick] = set()
    for module in modules:
        if module.always:
            continue
        if module.select == "pick":
            chosen = picks.get(module.id, module.default)
            ticks |= {("pkg", module.id, name) for name in chosen}
        else:
            ticks.add(("mod", module.id))
    return ticks


def selection(catalog: Catalog, ticks: set[Tick]) -> tuple[list[str], dict[str, list[str]]]:
    """Ticked rows -> (module ids, picks), dependency-closed like apply sees it.

    A pick module counts as selected when at least one of its apps is ticked.
    """
    wanted: list[str] = []
    picks: dict[str, list[str]] = {}
    for module in catalog.modules.values():
        if module.always:
            continue
        if module.select == "pick":
            chosen = [p.name for p in module.packages if ("pkg", module.id, p.name) in ticks]
            if chosen:
                wanted.append(module.id)
                picks[module.id] = chosen
        elif ("mod", module.id) in ticks:
            wanted.append(module.id)
    resolved = catalog.resolve(only=wanted)
    return [m.id for m in resolved if not m.always], picks


def rows(catalog: Catalog, system: System, ticks: set[Tick], t: dict[str, str]) -> list[Row]:
    """The apps list: one group per pick module, then the atomic modules."""
    out: list[Row] = []
    optional = [m for m in catalog.modules.values() if not m.always]
    for module in (m for m in optional if m.select == "pick"):
        out.append(Row(module.name))
        for p in module.packages:
            value = ("pkg", module.id, p.name)
            note = t["installed"] if system.has(p.name, cask=p.cask) else ""
            out.append(Row(p.label, value, value in ticks, note))

    atomic = [m for m in optional if m.select != "pick"]
    if atomic:
        out.append(Row(t["tools"]))
    for module in atomic:
        value = ("mod", module.id)
        if module.packages:
            label = f"{module.name}: {', '.join(p.label for p in module.packages)}"
        else:
            label = f"{module.name} — {module.description}" if module.description else module.name
        installed = bool(module.packages) and all(
            system.has(p.name, cask=p.cask) for p in module.packages
        )
        out.append(Row(label, value, value in ticks, t["installed"] if installed else ""))
    return out


def _ask_profile(catalog: Catalog, profile: str, t: dict[str, str]) -> str:
    choices = []
    for name, entries in catalog.profiles.items():
        if entries == ["*"]:
            summary = t["everything"]
        else:
            summary = t["group"] if len(entries) == 1 else t["groups"].format(n=len(entries))
        modules = [m for m in catalog.resolve(name) if not m.always]
        choices.append(
            Choice(
                title=f"{name:<10} {summary}",
                value=name,
                # Shown under the menu for the highlighted entry.
                description=", ".join(m.name for m in modules),
            )
        )
    choices.append(Choice(title=t["custom"], value=CUSTOM))
    choices.append(Choice(title=t["back"], value=BACK))
    questionary.print(f"  {t['purpose_hint']}", style="fg:#888888")
    return _ask(
        questionary.select(
            t["purpose"],
            choices=choices,
            default=next((c for c in choices if c.value == profile), None),
            style=_STYLE,
        )
    )


def _ask_apps(catalog: Catalog, system: System, ticks: set[Tick], t: dict[str, str]) -> set[Tick]:
    always = [m.name for m in catalog.modules.values() if m.always]
    if always:
        questionary.print(f"  {t['always'].format(names=', '.join(always))}", style="fg:#888888")
    answer = toggle_list(
        t["apps"], t["apps_hint"], rows(catalog, system, ticks, t), t["done"], t["ticked"]
    )
    if answer is None:
        raise WizardAborted("cancelled")
    return set(answer)


def _review(catalog: Catalog, machine: str, ticks: set[Tick], t: dict[str, str]) -> str:
    """Summarise the answers and ask whether to save or go back to a step."""
    modules, picks = selection(catalog, ticks)
    lines = []
    pulled = []
    for module_id in modules:
        module = catalog.modules[module_id]
        if module_id in picks:
            labels = [p.label for p in module.packages if p.name in picks[module_id]]
            lines.append(f"{module.name}: {', '.join(labels)}")
        elif ("mod", module_id) in ticks:
            lines.append(module.name)
        else:
            pulled.append(module.name)  # only here because something requires it

    questionary.print(f"\n  {t['machine']:<8} {machine}", style="bold")
    for i, line in enumerate(lines or [t["nothing"]]):
        questionary.print(f"  {t['apps_label'] if i == 0 else '':<8} {line}", style="bold")
    if pulled:
        questionary.print(f"  {t['required'].format(names=', '.join(pulled))}", style="fg:yellow")

    choices = [
        Choice(title=t["save"], value=SAVE),
        Choice(title=t["change_name"], value="name"),
        Choice(title=t["change_apps"], value="apps"),
        Choice(title=t["change_purpose"], value="profile"),
    ]
    return _ask(questionary.select(t["review"], choices=choices, style=_STYLE))
