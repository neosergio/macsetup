"""Wizard tests.

The prompts need a real terminal, so they are stubbed: questionary's text and
select get canned answers, and the apps list (`toggle_list`) gets a function
that decides what is ticked when "Done" is chosen. The tests assert on what
the wizard *offers* (rows, pre-ticks) and what it returns -- that is where the
logic lives. The list widget itself is driven for real in test_prompts.py.
"""

from __future__ import annotations

import pytest

from macsetup import wizard
from macsetup.detect import System
from macsetup.manifest import Catalog, Module
from macsetup.runner import FakeRunner, Result
from macsetup.state import MachineState


class Answer:
    """Stands in for a questionary prompt object."""

    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(
        modules={
            "core": Module(id="core", name="Core", always=True, packages=["git"]),
            "cli": Module(id="cli", name="CLI", packages=["tree"]),
            "editors": Module(
                id="editors",
                name="Editors",
                select="pick",
                default=["zed"],
                packages=["zed", {"name": "neovim", "title": "Neovim"}],
            ),
            "media": Module(id="media", name="Media", packages=["vlc"]),
        },
        profiles={"work": ["cli", "editors"], "personal": ["media"]},
    )


@pytest.fixture
def system() -> System:
    return System(arch="arm64", macos="26.5.1", brew=True, formulae=frozenset({"tree"}))


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner(responses={"scutil --get ComputerName": Result(0, "test-mbp\n")})


def keep(rows):
    """Choose "Done" without touching anything."""
    return [r.value for r in rows if r.value is not None and r.checked]


def tick(*values):
    """Choose "Done" with exactly these rows ticked."""
    return lambda rows: [r.value for r in rows if r.value in values]


def stub(monkeypatch, *, selects, apps, texts=()):
    """Feed canned answers. Returns the rows each apps list was offered.

    `selects` answers the menus in order (the purpose question, if asked,
    then the review screen); `apps` answers each apps list; `texts` answers
    the name prompt, falling back to its default.
    """
    offered: list[list] = []
    selects, apps, texts = list(selects), list(apps), list(texts)

    def fake_toggle(_message, _hint, rows, _done, _summary):
        offered.append(rows)
        return apps.pop(0)(rows)

    def fake_text(_message, default=None, **_kw):
        return Answer(texts.pop(0) if texts else default)

    monkeypatch.setattr(wizard.questionary, "text", fake_text)
    monkeypatch.setattr(wizard.questionary, "select", lambda *a, **k: Answer(selects.pop(0)))
    monkeypatch.setattr(wizard.questionary, "print", lambda *a, **k: None)
    monkeypatch.setattr(wizard, "toggle_list", fake_toggle)
    return offered


def ticked(rows):
    return {r.value for r in rows if r.value is not None and r.checked}


# --------------------------------------------------------------------------- #
# What the apps list offers


def test_profile_preticks_its_apps(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner)

    assert ticked(offered[0]) == {("mod", "cli"), ("pkg", "editors", "zed")}


def test_pick_modules_become_groups_of_apps(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner)

    labels = [r.label for r in offered[0]]
    # A header, then one row per app -- shown by title when it has one.
    assert labels[:3] == ["Editors", "zed", "Neovim"]
    assert offered[0][0].value is None


def test_atomic_modules_are_one_row_each_under_tools(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner)

    rows = {r.value: r for r in offered[0] if r.value is not None}
    assert rows[("mod", "cli")].label == "CLI: tree"
    assert rows[("mod", "cli")].note == "(installed)"
    assert "Tools" in [r.label for r in offered[0] if r.value is None]


def test_always_modules_are_not_offered(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner)

    assert not [r for r in offered[0] if r.value and r.value[1] == "core"]


def test_custom_start_preticks_nothing(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=[wizard.CUSTOM, wizard.SAVE], apps=[tick(("mod", "media"))])
    wizard.run(catalog, system, runner)

    assert ticked(offered[0]) == set()


# --------------------------------------------------------------------------- #
# A machine that is already configured


def test_configured_machine_skips_the_purpose_question(monkeypatch, catalog, system, runner):
    current = MachineState(machine="old", profile="work", modules=["media"], picks={})
    # Only the review menu is answered; a purpose question would pop SAVE.
    offered = stub(monkeypatch, selects=[wizard.SAVE], apps=[keep])
    result = wizard.run(catalog, system, runner, current=current)

    # 'media' is not in the work profile, but it is what this machine has.
    assert ticked(offered[0]) == {("mod", "media")}
    assert result.modules == ["media"]


def test_existing_picks_win_over_module_defaults(monkeypatch, catalog, system, runner):
    current = MachineState(
        machine="m", profile="work", modules=["editors"], picks={"editors": ["neovim"]}
    )
    offered = stub(monkeypatch, selects=[wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner, current=current)

    assert ticked(offered[0]) == {("pkg", "editors", "neovim")}


def test_empty_current_selection_falls_back_to_the_profile(monkeypatch, catalog, system, runner):
    # Pre-ticking nothing makes "Done" save nothing, which would keep an empty
    # machine.toml empty forever.
    current = MachineState(machine="m", profile="work", modules=[], picks={})
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner, current=current)

    assert ticked(offered[0]) == {("mod", "cli"), ("pkg", "editors", "zed")}


# --------------------------------------------------------------------------- #
# What gets returned


def test_result_records_selection(monkeypatch, catalog, system, runner):
    stub(
        monkeypatch,
        texts=["test-mbp"],
        selects=["work", wizard.SAVE],
        apps=[tick(("mod", "cli"), ("pkg", "editors", "neovim"))],
    )
    result = wizard.run(catalog, system, runner)

    assert result.machine == "test-mbp"
    assert result.profile == "work"
    assert set(result.modules) == {"cli", "editors"}
    assert result.picks == {"editors": ["neovim"]}
    # `always` modules are implicit, not stored.
    assert "core" not in result.modules


def test_pick_module_with_nothing_ticked_is_not_selected(monkeypatch, catalog, system, runner):
    stub(monkeypatch, selects=["work", wizard.SAVE], apps=[tick(("mod", "cli"))])
    result = wizard.run(catalog, system, runner)

    assert result.modules == ["cli"]
    assert result.picks == {}


def test_requires_are_pulled_in(monkeypatch, system, runner):
    catalog = Catalog(
        modules={
            "cli": Module(id="cli", name="CLI", packages=["tree"]),
            "python": Module(id="python", name="Python", requires=["cli"], packages=["uv"]),
        },
        profiles={"work": ["python"]},
    )
    stub(monkeypatch, selects=["work", wizard.SAVE], apps=[tick(("mod", "python"))])
    result = wizard.run(catalog, system, runner)

    assert set(result.modules) == {"cli", "python"}


# --------------------------------------------------------------------------- #
# Navigation


def test_back_from_purpose_returns_to_the_name(monkeypatch, catalog, system, runner):
    stub(
        monkeypatch,
        texts=["first", "second"],
        selects=[wizard.BACK, "work", wizard.SAVE],
        apps=[keep],
    )
    result = wizard.run(catalog, system, runner)

    assert result.machine == "second"
    assert result.profile == "work"


def test_review_can_change_apps_keeping_what_was_ticked(monkeypatch, catalog, system, runner):
    offered = stub(
        monkeypatch,
        selects=["work", "apps", wizard.SAVE],
        apps=[tick(("mod", "cli")), tick(("mod", "cli"), ("mod", "media"))],
    )
    result = wizard.run(catalog, system, runner)

    # The second time round, what was ticked before is ticked again --
    # not the profile's suggestion, which would undo the first answer.
    assert ticked(offered[1]) == {("mod", "cli")}
    assert set(result.modules) == {"cli", "media"}


def test_renaming_from_review_does_not_ask_for_apps_again(monkeypatch, catalog, system, runner):
    offered = stub(
        monkeypatch,
        texts=["first", "renamed"],
        selects=["work", "name", wizard.SAVE],
        apps=[keep],
    )
    result = wizard.run(catalog, system, runner)

    assert len(offered) == 1
    assert result.machine == "renamed"


def test_another_suggestion_replaces_the_ticks(monkeypatch, catalog, system, runner):
    offered = stub(
        monkeypatch,
        selects=["work", "profile", "personal", wizard.SAVE],
        apps=[keep, keep],
    )
    result = wizard.run(catalog, system, runner)

    assert ticked(offered[1]) == {("mod", "media")}
    assert result.profile == "personal"
    assert result.modules == ["media"]
    assert result.picks == {}


def test_configured_machine_can_start_from_a_suggestion(monkeypatch, catalog, system, runner):
    current = MachineState(machine="m", profile="work", modules=["media"], picks={})
    offered = stub(
        monkeypatch,
        selects=["profile", "work", wizard.SAVE],
        apps=[keep, keep],
    )
    result = wizard.run(catalog, system, runner, current=current)

    # Same profile name, but asked for explicitly: its suggestion replaces
    # the machine's selection.
    assert ticked(offered[1]) == {("mod", "cli"), ("pkg", "editors", "zed")}
    assert set(result.modules) == {"cli", "editors"}


def test_cancelling_raises(monkeypatch, catalog, system, runner):
    monkeypatch.setattr(wizard.questionary, "text", lambda *a, **k: Answer(None))
    with pytest.raises(wizard.WizardAborted):
        wizard.run(catalog, system, runner)


def test_cancelling_the_apps_list_raises(monkeypatch, catalog, system, runner):
    stub(monkeypatch, selects=["work"], apps=[lambda rows: None])
    with pytest.raises(wizard.WizardAborted):
        wizard.run(catalog, system, runner)


def test_spanish_labels(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner, lang="es")

    assert "Herramientas" in [r.label for r in offered[0] if r.value is None]
    rows = {r.value: r for r in offered[0] if r.value is not None}
    assert rows[("mod", "cli")].note == "(instalado)"


# --------------------------------------------------------------------------- #
# Installed vs chosen, and what an edit drops


def test_installed_rows_are_flagged_while_unticked(monkeypatch, catalog, system, runner):
    offered = stub(monkeypatch, selects=["work", wizard.SAVE], apps=[keep])
    wizard.run(catalog, system, runner)

    rows = {r.value: r for r in offered[0] if r.value is not None}
    # tree is installed: the row carries both notes, the widget picks by tick.
    assert (rows[("mod", "cli")].note, rows[("mod", "cli")].note_off) == (
        "(installed)",
        "(installed, not chosen)",
    )
    # Not installed: nothing to flag either way.
    assert (rows[("mod", "media")].note, rows[("mod", "media")].note_off) == ("", "")


def test_removed_lists_what_the_machine_had(catalog):
    before = {("mod", "cli"), ("pkg", "editors", "zed"), ("pkg", "editors", "neovim")}
    after = {("pkg", "editors", "neovim")}
    assert wizard.removed(catalog, before, after) == ["CLI", "zed"]


def test_removed_ignores_modules_still_pulled_in(system):
    catalog = Catalog(
        modules={
            "cli": Module(id="cli", name="CLI", packages=["tree"]),
            "python": Module(id="python", name="Python", requires=["cli"], packages=["uv"]),
        },
        profiles={"work": ["python"]},
    )
    before = {("mod", "cli"), ("mod", "python")}
    # cli unticked, but python requires it, so it is still applied.
    assert wizard.removed(catalog, before, {("mod", "python")}) == []


def test_review_warns_about_removals_on_a_configured_machine(monkeypatch, catalog, system, runner):
    printed: list[str] = []
    current = MachineState(
        machine="m", profile="work", modules=["cli", "editors"], picks={"editors": ["zed"]}
    )
    stub(monkeypatch, selects=[wizard.SAVE], apps=[tick(("pkg", "editors", "zed"))])
    monkeypatch.setattr(wizard.questionary, "print", lambda text, **k: printed.append(text))
    wizard.run(catalog, system, runner, current=current)

    assert any("Removed from the selection: CLI" in line for line in printed)


def test_first_run_has_nothing_to_report_as_removed(monkeypatch, catalog, system, runner):
    printed: list[str] = []
    stub(monkeypatch, selects=["work", wizard.SAVE], apps=[tick(("mod", "media"))])
    monkeypatch.setattr(wizard.questionary, "print", lambda text, **k: printed.append(text))
    wizard.run(catalog, system, runner)

    # Unticking the profile's suggestion is not removing anything the Mac had.
    assert not any("Removed" in line for line in printed)
