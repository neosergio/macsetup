from __future__ import annotations

from macsetup import state as state_mod
from macsetup.runner import FakeRunner, Result
from macsetup.state import MachineState
from macsetup.wizard import default_machine_name


def test_round_trip(tmp_path):
    path = tmp_path / "machine.toml"
    original = MachineState(
        machine="work-m3",
        profile="work",
        modules=["cli", "editors"],
        picks={"editors": ["zed", "neovim"]},
        vars={"git_email": "you@example.com"},
    )
    state_mod.save(original, path)
    loaded = state_mod.load(path)

    assert loaded is not None
    assert loaded.machine == original.machine
    assert loaded.profile == original.profile
    assert loaded.modules == original.modules
    assert loaded.vars == original.vars
    assert loaded.picks_as_sets() == original.picks_as_sets()


def test_picks_are_written_sorted(tmp_path):
    # Deterministic output: five machines writing the same selection should
    # produce byte-identical files, so a real change is easy to spot.
    path = tmp_path / "machine.toml"
    state_mod.save(
        MachineState(machine="m", profile="work", picks={"editors": ["zed", "neovim"]}), path
    )
    assert state_mod.load(path).picks == {"editors": ["neovim", "zed"]}


def test_load_missing_file_returns_none(tmp_path):
    assert state_mod.load(tmp_path / "absent.toml") is None


def test_saved_file_is_human_editable(tmp_path):
    path = tmp_path / "machine.toml"
    state_mod.save(MachineState(machine="m", profile="work", modules=["cli"]), path)
    text = path.read_text()

    assert text.startswith("#")
    assert 'machine = "m"' in text


def test_empty_picks_and_vars_are_omitted(tmp_path):
    path = tmp_path / "machine.toml"
    state_mod.save(MachineState(machine="m", profile="minimal", modules=[]), path)
    text = path.read_text()

    assert "picks" not in text
    assert "vars" not in text


def test_picks_as_sets():
    state = MachineState(machine="m", profile="work", picks={"editors": ["zed", "zed"]})
    assert state.picks_as_sets() == {"editors": {"zed"}}


def test_config_dir_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MACSETUP_CONFIG", str(tmp_path / "custom"))
    assert state_mod.config_dir() == tmp_path / "custom"


def test_config_dir_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("MACSETUP_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert state_mod.config_dir() == tmp_path / "macsetup"


def test_machine_name_prefers_computer_name():
    runner = FakeRunner(responses={"scutil --get ComputerName": Result(0, "Work MBP\n")})
    assert default_machine_name(runner) == "Work MBP"


def test_machine_name_falls_back_when_scutil_fails():
    runner = FakeRunner(default=Result(1, "", "boom"))
    assert default_machine_name(runner)  # hostname, whatever it is
