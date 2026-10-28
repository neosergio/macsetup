from __future__ import annotations

from macsetup import brewfile
from macsetup.detect import System, detect
from macsetup.manifest import Module, Package
from macsetup.planner import build_plan, untracked
from macsetup.runner import FakeRunner, Result


def system(*, formulae=(), casks=()) -> System:
    return System(
        arch="arm64",
        macos="26.5.1",
        brew=True,
        formulae=frozenset(formulae),
        casks=frozenset(casks),
    )


def module(module_id: str, packages, **kwargs) -> Module:
    return Module(id=module_id, name=module_id, packages=packages, **kwargs)


def test_missing_and_satisfied_are_split():
    mod = module("cli", ["tree", "jq"])
    plan = build_plan([mod], system(formulae=["tree"]))

    (only,) = plan.modules
    assert [p.name for p in only.missing] == ["jq"]
    assert [p.name for p in only.satisfied] == ["tree"]
    assert plan.missing_count == 1
    assert not plan.converged


def test_formula_and_cask_namespaces_do_not_collide():
    # `docker` exists as both a formula and a cask; an installed formula must
    # not satisfy a cask requirement.
    mod = module("containers", [{"name": "docker", "cask": True}])
    plan = build_plan([mod], system(formulae=["docker"]))
    assert [p.name for p in plan.modules[0].missing] == ["docker"]

    plan = build_plan([mod], system(casks=["docker"]))
    assert plan.converged


def test_converged_machine_has_nothing_pending():
    mod = module("cli", ["tree"])
    plan = build_plan([mod], system(formulae=["tree"]))
    assert plan.converged
    assert plan.pending == []


def test_unpicked_packages_are_skipped_not_missing():
    mod = module("editors", ["zed", "neovim"], select="pick", default=["zed"])
    plan = build_plan([mod], system())

    (only,) = plan.modules
    assert [p.name for p in only.missing] == ["zed"]
    assert [p.name for p in only.skipped] == ["neovim"]


def test_a_tapped_package_is_satisfied_by_its_short_name():
    # The manifest says neosergio/tap/git-wrong-email so brew bundle can tap
    # it; `brew list` reports it as git-wrong-email.
    mod = module("core", ["neosergio/tap/git-wrong-email"])
    plan = build_plan([mod], system(formulae=["git-wrong-email"]))
    assert plan.converged


def test_explicit_picks_override_defaults():
    mod = module("editors", ["zed", "neovim"], select="pick", default=["zed"])
    plan = build_plan([mod], system(), picks={"editors": {"neovim"}})
    assert [p.name for p in plan.modules[0].missing] == ["neovim"]


def test_untracked_reports_only_unaccounted_packages():
    mod = module("cli", ["tree"])
    state = system(formulae=["tree", "tmux"], casks=["iterm2"])
    formulae, casks = untracked(build_plan([mod], state), state)
    assert formulae == ["tmux"]
    assert casks == ["iterm2"]


def test_untracked_accounts_for_tapped_packages():
    mod = module("core", ["neosergio/tap/git-wrong-email"])
    state = system(formulae=["git-wrong-email"])
    assert untracked(build_plan([mod], state), state) == ([], [])


def test_detect_runs_brew_list_exactly_twice():
    # Idempotency depends on this: 60 packages must not mean 60 subprocesses.
    runner = FakeRunner(
        responses={
            "brew list --formula -1": Result(0, "tree\nuv\n"),
            "brew list --cask -1": Result(0, "iterm2\n"),
        }
    )
    state = detect(runner)

    assert state.formulae == frozenset({"tree", "uv"})
    assert state.casks == frozenset({"iterm2"})
    assert sum(1 for call in runner.calls if call[:2] == ["brew", "list"]) == 2


def test_detect_without_brew_reports_absent():
    runner = FakeRunner(default=Result(1, "", "not found"))
    state = detect(runner)
    assert state.brew is False
    assert state.formulae == frozenset()


def test_brewfile_groups_formulae_before_casks():
    text = brewfile.render(
        [Package(name="arc", cask=True), Package(name="git"), Package(name="zed", cask=True)]
    )
    assert text.splitlines() == ['brew "git"', 'cask "arc"', 'cask "zed"']


def test_install_defaults_to_no_upgrade():
    runner = FakeRunner()
    brewfile.install(runner, "/tmp/x.Brewfile")
    assert "--no-upgrade" in runner.calls[0]


def test_install_can_opt_into_upgrade():
    runner = FakeRunner()
    brewfile.install(runner, "/tmp/x.Brewfile", upgrade=True, jobs=4)
    assert "--no-upgrade" not in runner.calls[0]
    assert "--jobs=4" in runner.calls[0]
