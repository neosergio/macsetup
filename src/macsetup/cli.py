"""Command surface.

Every wizard answer has a flag equivalent, so any machine can be provisioned
non-interactively. The wizard is for *deciding*; apply is for *converging*.

Selection precedence: --only beats --profile beats saved machine state.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import brewfile, wizard
from . import files as files_mod
from . import state as state_mod
from .detect import System, detect
from .manifest import Catalog, ManifestError, Module, files_dir, load_catalog
from .planner import Plan, build_plan, untracked
from .runner import SubprocessRunner
from .state import MachineState, builtin_vars

app = typer.Typer(
    add_completion=True,
    no_args_is_help=True,
    help="Provision a MacBook from declarative manifests.",
)
console = Console()

ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", "-p", help="Profile to resolve. Defaults to saved machine state."),
]
OnlyOpt = Annotated[
    list[str] | None,
    typer.Option("--only", help="Limit to these modules (repeatable). Skips `always` modules."),
]


@dataclass
class Selection:
    modules: list[Module]
    picks: dict[str, set[str]] = field(default_factory=dict)
    source: str = ""
    machine: MachineState | None = None

    def template_vars(self) -> dict[str, str]:
        if self.machine:
            return self.machine.template_vars()
        # No machine.toml yet (--profile on a fresh box): fall back to the
        # hostname so `render` steps still work before `init` has been run.
        return builtin_vars(wizard.default_machine_name(SubprocessRunner()))


def _build(selection: Selection, system: System) -> Plan:
    try:
        root = files_dir()
    except ManifestError:
        root = None
    return build_plan(
        selection.modules,
        system,
        selection.picks,
        files_root=root,
        variables=selection.template_vars(),
    )


def _load() -> Catalog:
    try:
        return load_catalog()
    except ManifestError as exc:
        console.print(f"[red]manifest error:[/] {exc}")
        raise typer.Exit(2) from exc


def _system(*, require_brew: bool = True) -> System:
    system = detect(SubprocessRunner())
    if require_brew and not system.brew:
        console.print("[red]Homebrew not found.[/] Install it from https://brew.sh first.")
        raise typer.Exit(1)
    return system


def _select(catalog: Catalog, profile: str | None, only: list[str] | None) -> Selection:
    machine = state_mod.load()
    try:
        if only:
            picks = machine.picks_as_sets() if machine else {}
            return Selection(catalog.resolve(only=only), picks, f"modules {', '.join(only)}")
        if profile:
            picks = machine.picks_as_sets() if machine and machine.profile == profile else {}
            return Selection(catalog.resolve(profile), picks, f"profile {profile}")
        if machine:
            if not machine.modules:
                console.print(
                    "[yellow]This machine selects no optional modules[/] — only the "
                    "always-on ones apply. Run [bold]macsetup configure[/] to pick some."
                )
            modules = catalog.resolve(only=machine.modules, include_always=True)
            return Selection(
                modules,
                machine.picks_as_sets(),
                f"machine {machine.machine} (profile {machine.profile})",
                machine,
            )
    except ManifestError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    console.print(
        "[red]No machine state and no --profile.[/] "
        "Run [bold]macsetup init[/] once on this machine, or pass --profile."
    )
    raise typer.Exit(2)


def _plan_table(plan: Plan) -> Table:
    table = Table(box=None, pad_edge=False)
    table.add_column("", width=2)
    table.add_column("module", style="bold")
    table.add_column("package")
    table.add_column("kind", style="dim")

    for module_plan in plan.modules:
        first = True
        for package in module_plan.missing:
            table.add_row(
                "[green]+[/]",
                module_plan.module.id if first else "",
                package.name,
                "cask" if package.cask else "formula",
            )
            first = False
        for action in module_plan.pending_files:
            verb = "[green]+[/]" if action.outcome.status is files_mod.FileStatus.CREATE else "~"
            table.add_row(
                verb,
                module_plan.module.id if first else "",
                str(action.outcome.dest).replace(str(Path.home()), "~"),
                action.spec.kind,
            )
            first = False
        if module_plan.pending:
            continue
        detail = f"{len(module_plan.satisfied)} package(s) already installed"
        if module_plan.file_actions and not module_plan.satisfied:
            detail = f"{len(module_plan.file_actions)} file(s) up to date"
        table.add_row("[dim]=[/]", f"[dim]{module_plan.module.id}[/]", f"[dim]{detail}[/]", "")
    return table


def _summarise(plan: Plan) -> None:
    if plan.converged:
        have = []
        if plan.satisfied_count:
            have.append(f"{plan.satisfied_count} package(s)")
        file_count = sum(len(m.file_actions) for m in plan.modules)
        if file_count:
            have.append(f"{file_count} file(s)")
        console.print(f"[green]Converged.[/] {', '.join(have) or 'Nothing selected'} up to date.")
        return
    bits = []
    if plan.missing_count:
        bits.append(f"[bold]{plan.missing_count}[/] package(s) to install")
    if plan.file_change_count:
        bits.append(f"[bold]{plan.file_change_count}[/] file(s) to write")
    console.print(f"{', '.join(bits)}, across {len(plan.pending)} module(s).")


def _apply_files(module_plan, root: Path, variables: dict[str, str]) -> None:
    for action in module_plan.pending_files:
        spec = action.spec
        dest = action.outcome.dest
        source = root / spec.source
        if spec.kind == "copy":
            files_mod.apply_copy(source, dest, spec.mode)
        elif spec.kind == "render":
            files_mod.apply_render(source, dest, variables, spec.mode)
        else:
            files_mod.apply_block(
                dest,
                source.read_text(encoding="utf-8"),
                comment=spec.comment,
                position=spec.position,
                mode=spec.mode,
            )
        console.print(f"  [green]wrote[/] {str(dest).replace(str(Path.home()), '~')}")


def _install(plan: Plan, selection: Selection, *, upgrade: bool, jobs: int | None) -> None:
    runner = SubprocessRunner()
    failed: list[str] = []
    targets = plan.modules if upgrade else plan.pending
    variables = selection.template_vars()
    root = files_dir()

    for module_plan in targets:
        console.rule(f"[bold]{module_plan.module.id}[/]")
        packages = module_plan.selected
        if packages and (module_plan.missing or upgrade):
            path = brewfile.write(module_plan.module.id, packages)
            if not brewfile.install(runner, path, upgrade=upgrade, jobs=jobs).ok:
                failed.append(module_plan.module.id)
                console.print(f"[red]{module_plan.module.id} failed[/] (Brewfile kept at {path})")
                # Files often configure what the packages provide, so skip them
                # rather than pointing a shell fragment at a missing binary.
                continue
        try:
            _apply_files(module_plan, root, variables)
        except OSError as exc:
            failed.append(module_plan.module.id)
            console.print(f"[red]{module_plan.module.id} file step failed:[/] {exc}")

    console.rule()
    if failed:
        console.print(f"[red]Failed modules:[/] {', '.join(failed)}")
        raise typer.Exit(1)
    console.print("[green]Done.[/]")


def _run_wizard(catalog: Catalog, current: MachineState | None) -> MachineState:
    # prompt_toolkit throws a bare OSError when there is no usable terminal
    # (piped stdin, ssh without -t, CI). Catch it here so the flag-based path
    # is discoverable instead of dumping a traceback.
    if not sys.stdin.isatty():
        console.print(
            "[red]The wizard needs an interactive terminal.[/]\n"
            "Non-interactively, every answer has a flag: "
            "[bold]macsetup apply --profile work --yes[/]"
        )
        raise typer.Exit(2)

    system = _system()
    try:
        chosen = wizard.run(catalog, system, SubprocessRunner(), current=current)
    except wizard.WizardAborted:
        console.print("[yellow]Cancelled.[/] Nothing was saved.")
        raise typer.Exit(130) from None
    except (OSError, EOFError) as exc:
        # repr, not str: EOFError stringifies to nothing, which leaves the
        # message ending in a bare colon.
        console.print(f"[red]Could not read from the terminal:[/] {exc!r}")
        raise typer.Exit(2) from exc

    # Enter on an untouched checkbox selects nothing, which is a legitimate
    # answer but almost never the intended one -- and it is what the caller is
    # about to write over the existing selection.
    if not chosen.modules and not typer.confirm(
        "Nothing selected — only the always-on modules would apply. Save that?",
        default=False,
    ):
        console.print("[yellow]Cancelled.[/] Nothing was saved.")
        raise typer.Exit(130)
    return chosen


# --------------------------------------------------------------------------- #


@app.command("modules")
def list_modules() -> None:
    """List every module and profile in the catalog."""
    catalog = _load()

    table = Table(title="modules", box=None, pad_edge=False)
    table.add_column("id", style="bold")
    table.add_column("select", style="dim")
    table.add_column("installs")
    table.add_column("description", style="dim")
    for module in catalog.modules.values():
        flags = module.select + (" · always" if module.always else "")
        table.add_row(module.id, flags, wizard.module_contents(module), module.description)
    console.print(table)

    profiles = Table(title="profiles", box=None, pad_edge=False)
    profiles.add_column("name", style="bold")
    profiles.add_column("modules")
    for name, entries in catalog.profiles.items():
        profiles.add_row(name, "all" if entries == ["*"] else ", ".join(entries))
    console.print()
    console.print(profiles)


@app.command()
def init(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip install confirmation.")] = False,
    no_apply: Annotated[
        bool, typer.Option("--no-apply", help="Save the selection without installing.")
    ] = False,
) -> None:
    """First-run wizard: choose modules, save machine state, then install."""
    catalog = _load()
    current = state_mod.load()
    if current:
        console.print(
            f"[yellow]This machine is already configured[/] as "
            f"[bold]{current.machine}[/]; re-running with your current answers."
        )

    chosen = _run_wizard(catalog, current)
    path = state_mod.save(chosen)
    console.print(f"\nSaved [bold]{path}[/]")

    if no_apply:
        console.print("Run [bold]macsetup apply[/] when ready.")
        return

    modules = catalog.resolve(only=chosen.modules, include_always=True)
    selection = Selection(modules, chosen.picks_as_sets(), "wizard", chosen)
    plan_result = _build(selection, _system())
    console.print()
    console.print(_plan_table(plan_result))
    console.print()
    _summarise(plan_result)

    if plan_result.converged:
        return
    if not yes and not typer.confirm(
        f"Install {plan_result.missing_count} package(s)?", default=True
    ):
        raise typer.Abort()
    _install(plan_result, selection, upgrade=False, jobs=None)


@app.command()
def configure() -> None:
    """Re-run the wizard to change this machine's selection. Installs nothing."""
    catalog = _load()
    chosen = _run_wizard(catalog, state_mod.load())
    path = state_mod.save(chosen)
    console.print(f"\nSaved [bold]{path}[/]")
    console.print("Run [bold]macsetup apply[/] to converge.")


@app.command()
def plan(
    profile: ProfileOpt = None,
    only: OnlyOpt = None,
    show_brewfile: Annotated[
        bool, typer.Option("--show-brewfile", help="Print the generated Brewfiles instead.")
    ] = False,
) -> None:
    """Show what apply would install. Changes nothing."""
    catalog = _load()
    selection = _select(catalog, profile, only)
    result = _build(selection, _system())

    if show_brewfile:
        for module_plan in result.modules:
            if not module_plan.selected:
                continue
            console.print(f"[bold]# {module_plan.module.id}.Brewfile[/]")
            console.print(brewfile.render(module_plan.selected))
        return

    console.print(f"[dim]{selection.source}[/]")
    console.print(_plan_table(result))
    console.print()
    _summarise(result)


@app.command()
def apply(
    profile: ProfileOpt = None,
    only: OnlyOpt = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Stop after the preview.")] = False,
    upgrade: Annotated[
        bool, typer.Option("--upgrade", help="Also upgrade outdated packages.")
    ] = False,
    jobs: Annotated[int | None, typer.Option("--jobs", help="Parallel formula installs.")] = None,
) -> None:
    """Install everything the selected modules require."""
    catalog = _load()
    selection = _select(catalog, profile, only)
    result = _build(selection, _system())

    console.print(f"[dim]{selection.source}[/]")
    console.print(_plan_table(result))
    console.print()

    if result.converged and not upgrade:
        console.print("[green]Nothing to do.[/]")
        return
    if dry_run:
        console.print(f"[yellow]Dry run.[/] {result.missing_count} package(s) would be installed.")
        return
    if not yes and not typer.confirm("Apply these changes?", default=True):
        raise typer.Abort()

    _install(result, selection, upgrade=upgrade, jobs=jobs)


@app.command()
def status(profile: ProfileOpt = None, only: OnlyOpt = None) -> None:
    """Drift report: manifest versus what is actually on this machine."""
    catalog = _load()
    selection = _select(catalog, profile, only)
    system = _system()
    result = _build(selection, system)

    console.print(
        f"[bold]{system.arch}[/] · macOS {system.macos} · "
        f"{system.installed_count} packages installed · {selection.source}"
    )
    console.print()

    table = Table(box=None, pad_edge=False)
    table.add_column("module", style="bold")
    table.add_column("state")
    table.add_column("detail", style="dim")
    for module_plan in result.modules:
        if module_plan.pending:
            bits = []
            if module_plan.missing:
                bits.append("missing: " + ", ".join(p.name for p in module_plan.missing))
            for action in module_plan.pending_files:
                target = str(action.outcome.dest).replace(str(Path.home()), "~")
                bits.append(f"{action.outcome.status.value} {target}")
            table.add_row(module_plan.module.id, "[yellow]drifted[/]", "; ".join(bits))
        else:
            counts = [f"{len(module_plan.satisfied)} package(s)"]
            if module_plan.file_actions:
                counts.append(f"{len(module_plan.file_actions)} file(s)")
            table.add_row(module_plan.module.id, "[green]ok[/]", ", ".join(counts))
    console.print(table)

    # Modules that were never adopted on this machine. Without this, a module
    # added upstream stays invisible forever.
    if selection.machine:
        machine_profile = selection.machine.profile
        unadopted = catalog.unadopted(machine_profile, (m.id for m in selection.modules))
        known = machine_profile in catalog.profiles
        scope = f"in profile '{machine_profile}'" if known else "available"
        if unadopted:
            console.print()
            console.print(
                f"[yellow]{len(unadopted)} module(s) {scope} "
                f"not selected here:[/] {', '.join(unadopted)}"
            )
            console.print("[dim]Run `macsetup configure` to adopt them.[/]")

    extra_formulae, extra_casks = untracked(result, system)
    extras = len(extra_formulae) + len(extra_casks)
    if extras:
        console.print()
        console.print(
            f"[dim]{extras} installed package(s) not covered by this selection "
            f"({len(extra_formulae)} formulae, {len(extra_casks)} casks). "
            f"Run `macsetup untracked` to list them.[/]"
        )


@app.command("untracked")
def untracked_cmd(profile: ProfileOpt = None, only: OnlyOpt = None) -> None:
    """List installed packages that no selected module accounts for."""
    catalog = _load()
    selection = _select(catalog, profile, only)
    system = _system()
    formulae, casks = untracked(_build(selection, system), system)

    if not formulae and not casks:
        console.print("[green]Everything installed is accounted for.[/]")
        return
    if formulae:
        console.print("[bold]formulae[/]")
        console.print("  " + "\n  ".join(formulae))
    if casks:
        console.print("[bold]casks[/]")
        console.print("  " + "\n  ".join(casks))
    console.print()
    console.print("[dim]Candidates to adopt into a module, or to remove once prune lands.[/]")


if __name__ == "__main__":
    app()
