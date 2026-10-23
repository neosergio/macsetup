from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from macsetup import files
from macsetup.files import BEGIN, END, FileStatus, compose_block


def test_copy_creates_then_is_idempotent(tmp_path):
    src = tmp_path / "src.zsh"
    src.write_text("export FOO=1\n")
    dest = tmp_path / "out" / "src.zsh"

    assert files.plan_copy(src, dest).status is FileStatus.CREATE
    files.apply_copy(src, dest)
    assert dest.read_text() == "export FOO=1\n"
    assert files.plan_copy(src, dest).status is FileStatus.OK


def test_copy_detects_a_hand_edit_as_update(tmp_path):
    src = tmp_path / "src.zsh"
    src.write_text("a\n")
    dest = tmp_path / "dest.zsh"
    dest.write_text("edited by hand\n")

    assert files.plan_copy(src, dest).status is FileStatus.UPDATE


def test_overwriting_an_existing_file_keeps_a_backup(tmp_path):
    src = tmp_path / "src"
    src.write_text("new\n")
    dest = tmp_path / "dest"
    dest.write_text("precious\n")

    files.apply_copy(src, dest)
    assert dest.read_text() == "new\n"
    assert (tmp_path / "dest.macsetup-bak").read_text() == "precious\n"


def test_backup_is_not_clobbered_on_a_second_run(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    dest.write_text("original\n")

    src.write_text("v1\n")
    files.apply_copy(src, dest)
    src.write_text("v2\n")
    files.apply_copy(src, dest)

    # The backup must still hold the user's file, not our v1.
    assert (tmp_path / "dest.macsetup-bak").read_text() == "original\n"


def test_mode_is_applied(tmp_path):
    src = tmp_path / "src"
    src.write_text("x\n")
    dest = tmp_path / "dest"
    files.apply_copy(src, dest, mode="600")

    assert oct(dest.stat().st_mode)[-3:] == "600"


def test_render_substitutes_variables(tmp_path):
    src = tmp_path / "t.j2"
    src.write_text("host {{ machine }} key {{ personal_key }}\n")
    dest = tmp_path / "out"

    files.apply_render(src, dest, {"machine": "mbp", "personal_key": "~/.ssh/id"})
    assert dest.read_text() == "host mbp key ~/.ssh/id\n"


def test_render_fails_loudly_on_a_missing_variable(tmp_path):
    # StrictUndefined: a typo'd variable must not silently render as empty.
    src = tmp_path / "t.j2"
    src.write_text("{{ nope }}\n")
    with pytest.raises(UndefinedError):
        files.render_template(src, {})


def test_render_is_idempotent(tmp_path):
    src = tmp_path / "t.j2"
    src.write_text("{{ machine }}\n")
    dest = tmp_path / "out"
    variables = {"machine": "m"}

    files.apply_render(src, dest, variables)
    assert files.plan_render(src, dest, variables).status is FileStatus.OK


# --------------------------------------------------------------------------- #
# Managed blocks


def test_block_into_empty_file_is_just_the_block():
    result = compose_block("", "source me\n")
    assert result == f"{BEGIN}\nsource me\n{END}\n"


def test_block_appends_and_preserves_existing_content():
    result = compose_block("export EDITOR=vim\n", "source me")

    assert result.startswith("export EDITOR=vim\n")
    assert BEGIN in result and END in result


def test_block_position_top_goes_first():
    # ssh_config takes the first value for each keyword, so Include must lead.
    result = compose_block("Host example\n\tUser me\n", "Include ~/.ssh/config.d/*", position="top")

    assert result.startswith(BEGIN)
    assert result.index(BEGIN) < result.index("Host example")


def test_block_replaces_in_place_without_touching_neighbours():
    original = compose_block("before\n", "v1")
    original = original + "after\n"

    updated = compose_block(original, "v2")

    assert "v1" not in updated
    assert "v2" in updated
    assert updated.startswith("before\n")
    assert updated.rstrip().endswith("after")
    # exactly one block, not two
    assert updated.count(BEGIN) == 1


def test_block_is_idempotent():
    once = compose_block("x\n", "body")
    twice = compose_block(once, "body")
    assert once == twice


def test_block_uses_the_configured_comment_character():
    result = compose_block("", "Include foo", comment="//")
    assert result.startswith("// >>> macsetup >>>")


def test_plan_block_reports_create_then_ok(tmp_path):
    dest = tmp_path / ".zshrc"
    assert files.plan_block(dest, "body").status is FileStatus.CREATE

    files.apply_block(dest, "body")
    assert files.plan_block(dest, "body").status is FileStatus.OK


def test_plan_block_reports_update_when_body_changes(tmp_path):
    dest = tmp_path / ".zshrc"
    files.apply_block(dest, "old body")
    outcome = files.plan_block(dest, "new body")

    assert outcome.status is FileStatus.UPDATE
    assert outcome.detail == "update block"


def test_apply_block_keeps_user_lines_outside_the_markers(tmp_path):
    dest = tmp_path / ".zshrc"
    dest.write_text("alias ll='ls -la'\n")

    files.apply_block(dest, "source fragments")
    files.apply_block(dest, "source fragments v2")

    text = dest.read_text()
    assert "alias ll='ls -la'" in text
    assert text.count(BEGIN) == 1


def test_expand_handles_tilde_and_env(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XYZ", "sub")
    assert files.expand("~/$XYZ/f") == tmp_path / "sub" / "f"


def test_every_render_in_the_catalog_resolves_with_default_vars():
    # Rendering uses StrictUndefined, so a template referencing a variable with
    # no default would only fail on a real machine, mid-apply. Catch it here:
    # every `render:` in the shipped catalog must render from defaults alone.
    from macsetup.manifest import files_dir, load_catalog, manifests_dir
    from macsetup.state import MachineState

    catalog = load_catalog(manifests_dir())
    variables = MachineState(machine="test", profile="custom").template_vars()
    root = files_dir()

    rendered = 0
    for module in catalog.modules.values():
        for spec in module.files:
            if spec.kind != "render":
                continue
            files.render_template(root / spec.source, variables)
            rendered += 1
    assert rendered, "no render: steps found -- has the catalog changed?"


def test_gitconfig_template_carries_the_machine_identity():
    from macsetup.manifest import files_dir
    from macsetup.state import MachineState

    state = MachineState(
        machine="work-laptop",
        profile="custom",
        vars={"git_email": "someone@example.com"},
    )
    out = files.render_template(files_dir() / "git/gitconfig.j2", state.template_vars())

    assert "email = someone@example.com" in out
    assert "name = Your Name" in out  # unset var falls back to the catalog default
    assert "Rendered on work-laptop" in out  # `machine` is always supplied
