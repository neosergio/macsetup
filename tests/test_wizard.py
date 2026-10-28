"""Wizard tests.

questionary needs a real terminal, so the prompt calls are stubbed and the
tests assert on what the wizard *asks* (which choices are pre-ticked) and what
it returns. That is where the logic actually lives.
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
                packages=["zed", "neovim"],
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


def stub(monkeypatch, *, text, select, checkboxes):
    """Feed canned answers; record the choices each checkbox was offered.

    `select` answers the menus in order: the profile, then the review screen.
    A single profile name is shorthand for picking it and saving at review.
    """
    seen: list[list] = []
    queue = list(checkboxes)
    selects = [select, wizard.SAVE] if isinstance(select, str) else list(select)
    texts = [text] if isinstance(text, str) else list(text)

    def fake_checkbox(_message, choices=None, **_kw):
        seen.append(choices or [])
        return Answer(queue.pop(0))

    def fake_text(_message, default=None, **_kw):
        return Answer(texts.pop(0) if texts else default)

    monkeypatch.setattr(wizard.questionary, "text", fake_text)
    monkeypatch.setattr(wizard.questionary, "select", lambda *a, **k: Answer(selects.pop(0)))
    monkeypatch.setattr(wizard.questionary, "checkbox", fake_checkbox)
    monkeypatch.setattr(wizard.questionary, "print", lambda *a, **k: None)
    return seen


def test_profile_preselects_its_modules(monkeypatch, catalog, system, runner):
    seen = stub(
        monkeypatch, text="test-mbp", select="work", checkboxes=[["cli", "editors"], ["zed"]]
    )
    wizard.run(catalog, system, runner)

    checked = {c.value for c in seen[0] if c.checked}
    assert checked == {"cli", "editors"}


def test_always_modules_are_not_offered_as_choices(monkeypatch, catalog, system, runner):
    seen = stub(monkeypatch, text="m", select="work", checkboxes=[["cli", "editors"], ["zed"]])
    wizard.run(catalog, system, runner)

    assert "core" not in {c.value for c in seen[0]}


def test_custom_profile_preselects_nothing(monkeypatch, catalog, system, runner):
    seen = stub(monkeypatch, text="m", select=wizard.CUSTOM, checkboxes=[[]])
    wizard.run(catalog, system, runner)

    assert not [c for c in seen[0] if c.checked]


def test_reconfigure_preselects_current_machine_not_profile(monkeypatch, catalog, system, runner):
    current = MachineState(machine="old", profile="work", modules=["media"], picks={})
    seen = stub(monkeypatch, text="old", select="work", checkboxes=[["media"]])
    wizard.run(catalog, system, runner, current=current)

    # 'media' is not in the work profile, but it is what this machine has.
    assert {c.value for c in seen[0] if c.checked} == {"media"}


def test_empty_current_selection_falls_back_to_the_profile(monkeypatch, catalog, system, runner):
    # Pre-ticking nothing makes a bare Enter save nothing, which would keep an
    # empty machine.toml empty forever.
    current = MachineState(machine="m", profile="work", modules=[], picks={})
    seen = stub(monkeypatch, text="m", select="work", checkboxes=[["cli", "editors"], ["zed"]])
    wizard.run(catalog, system, runner, current=current)

    assert {c.value for c in seen[0] if c.checked} == {"cli", "editors"}


def test_pick_module_offers_its_packages_with_defaults(monkeypatch, catalog, system, runner):
    seen = stub(monkeypatch, text="m", select="work", checkboxes=[["editors"], ["zed"]])
    wizard.run(catalog, system, runner)

    package_choices = seen[1]
    assert {c.value for c in package_choices} == {"zed", "neovim"}
    assert {c.value for c in package_choices if c.checked} == {"zed"}


def test_existing_picks_win_over_module_defaults(monkeypatch, catalog, system, runner):
    current = MachineState(
        machine="m", profile="work", modules=["editors"], picks={"editors": ["neovim"]}
    )
    seen = stub(monkeypatch, text="m", select="work", checkboxes=[["editors"], ["neovim"]])
    wizard.run(catalog, system, runner, current=current)

    assert {c.value for c in seen[1] if c.checked} == {"neovim"}


def test_result_records_selection(monkeypatch, catalog, system, runner):
    stub(monkeypatch, text="test-mbp", select="work", checkboxes=[["cli", "editors"], ["neovim"]])
    result = wizard.run(catalog, system, runner)

    assert result.machine == "test-mbp"
    assert result.profile == "work"
    assert set(result.modules) == {"cli", "editors"}
    assert result.picks == {"editors": ["neovim"]}
    # `always` modules are implicit, not stored.
    assert "core" not in result.modules


def test_requires_are_pulled_in(monkeypatch, system, runner):
    catalog = Catalog(
        modules={
            "cli": Module(id="cli", name="CLI", packages=["tree"]),
            "python": Module(id="python", name="Python", requires=["cli"], packages=["uv"]),
        },
        profiles={"work": ["python"]},
    )
    stub(monkeypatch, text="m", select="work", checkboxes=[["python"]])
    result = wizard.run(catalog, system, runner)

    assert set(result.modules) == {"cli", "python"}


def test_cancelling_raises(monkeypatch, catalog, system, runner):
    monkeypatch.setattr(wizard.questionary, "text", lambda *a, **k: Answer(None))
    with pytest.raises(wizard.WizardAborted):
        wizard.run(catalog, system, runner)


# --------------------------------------------------------------------------- #
# Navigation


def test_back_from_profile_returns_to_the_name(monkeypatch, catalog, system, runner):
    stub(
        monkeypatch,
        text=["first", "second"],
        select=[wizard.BACK, "work", wizard.SAVE],
        checkboxes=[["cli"]],
    )
    result = wizard.run(catalog, system, runner)

    assert result.machine == "second"
    assert result.profile == "work"


def test_review_can_change_modules_keeping_the_previous_answer(
    monkeypatch, catalog, system, runner
):
    seen = stub(
        monkeypatch,
        text="m",
        select=["work", "modules", wizard.SAVE],
        checkboxes=[["cli"], ["cli", "media"]],
    )
    result = wizard.run(catalog, system, runner)

    # The second time round, what was ticked before is ticked again --
    # not the profile's defaults, which would undo the first answer.
    assert {c.value for c in seen[1] if c.checked} == {"cli"}
    assert set(result.modules) == {"cli", "media"}


def test_review_can_redo_one_modules_picks(monkeypatch, catalog, system, runner):
    seen = stub(
        monkeypatch,
        text="m",
        select=["work", "pick:editors", wizard.SAVE],
        checkboxes=[["cli", "editors"], ["zed"], ["neovim"]],
    )
    result = wizard.run(catalog, system, runner)

    # Only the editors picks are asked again, pre-ticked with the first answer.
    assert len(seen) == 3
    assert {c.value for c in seen[2] if c.checked} == {"zed"}
    assert result.picks == {"editors": ["neovim"]}


def test_changing_profile_resets_module_preselection(monkeypatch, catalog, system, runner):
    seen = stub(
        monkeypatch,
        text="m",
        select=["work", "profile", "personal", wizard.SAVE],
        checkboxes=[["cli", "editors"], ["zed"], ["media"]],
    )
    result = wizard.run(catalog, system, runner)

    assert {c.value for c in seen[2] if c.checked} == {"media"}
    assert result.profile == "personal"
    assert result.modules == ["media"]
    # editors is no longer selected, so its picks are not saved.
    assert result.picks == {}


def test_review_offers_a_change_entry_per_pick_module(monkeypatch, catalog, system, runner):
    offered: list[list] = []
    selects = ["work", wizard.SAVE]

    def fake_select(_message, choices=None, **_kw):
        offered.append(choices or [])
        return Answer(selects.pop(0))

    stub(monkeypatch, text="m", select=[], checkboxes=[["cli", "editors"], ["zed"]])
    monkeypatch.setattr(wizard.questionary, "select", fake_select)
    wizard.run(catalog, system, runner)

    review = {c.value for c in offered[1]}
    assert {wizard.SAVE, "name", "profile", "modules", "pick:editors"} == review
