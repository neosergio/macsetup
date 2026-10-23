from __future__ import annotations

import pytest
from pydantic import ValidationError

from macsetup.manifest import Catalog, ManifestError, Module, Package, load_catalog


def module(module_id: str, **kwargs) -> Module:
    kwargs.setdefault("name", module_id)
    return Module(id=module_id, **kwargs)


def test_package_shorthand_is_a_formula():
    assert Package.model_validate("git") == Package(name="git", cask=False)


def test_package_brewfile_lines():
    assert Package(name="git").brewfile_line() == 'brew "git"'
    assert Package(name="arc", cask=True).brewfile_line() == 'cask "arc"'
    assert Package(name="Xcode", mas=497799835).brewfile_line() == 'mas "Xcode", id: 497799835'


def test_unknown_key_is_rejected():
    # A typo'd key must fail at load, not be silently ignored.
    with pytest.raises(ValidationError):
        Package.model_validate({"name": "git", "casks": True})


def test_default_must_reference_real_packages():
    with pytest.raises(ValidationError, match="unknown packages"):
        module("editors", select="pick", default=["nope"], packages=["neovim"])


def test_default_requires_select_pick():
    with pytest.raises(ValidationError, match="select: pick"):
        module("editors", default=["neovim"], packages=["neovim"])


def test_selected_packages_respects_picks():
    mod = module(
        "editors",
        select="pick",
        default=["zed"],
        packages=["zed", "neovim", "helix"],
    )
    assert [p.name for p in mod.selected_packages()] == ["zed"]
    assert [p.name for p in mod.selected_packages({"neovim", "helix"})] == ["neovim", "helix"]


def test_select_all_ignores_picks():
    mod = module("cli", packages=["tree", "jq"])
    assert [p.name for p in mod.selected_packages({"tree"})] == ["tree", "jq"]


def catalog() -> Catalog:
    return Catalog(
        modules={
            "core": module("core", always=True, packages=["git"]),
            "cli": module("cli", packages=["tree"]),
            "python": module("python", requires=["cli"], packages=["uv"]),
        },
        profiles={"work": ["python"], "full": ["*"]},
    )


def test_resolve_includes_always_modules():
    assert [m.id for m in catalog().resolve("work")] == ["core", "cli", "python"]


def test_resolve_expands_requires_before_dependent():
    resolved = [m.id for m in catalog().resolve("work")]
    assert resolved.index("cli") < resolved.index("python")


def test_resolve_star_profile_takes_everything():
    assert {m.id for m in catalog().resolve("full")} == {"core", "cli", "python"}


def test_only_skips_always_modules():
    # --only means "just this, I know what I want".
    assert [m.id for m in catalog().resolve(only=["cli"])] == ["cli"]


def test_only_still_pulls_requires():
    assert [m.id for m in catalog().resolve(only=["python"])] == ["cli", "python"]


def test_empty_only_is_a_selection_not_a_missing_one():
    # machine.toml with `modules = []` -- a configured machine that has adopted
    # nothing, not a machine with no state. Must not demand a profile.
    assert [m.id for m in catalog().resolve(only=[], include_always=True)] == ["core"]


def test_empty_only_without_always_resolves_to_nothing():
    assert catalog().resolve(only=[]) == []


def test_neither_profile_nor_module_list_is_an_error():
    with pytest.raises(ManifestError, match="need a profile"):
        catalog().resolve()


def test_unknown_profile_is_an_error():
    with pytest.raises(ManifestError, match="unknown profile"):
        catalog().resolve("nope")


def test_unknown_module_in_only_is_an_error():
    with pytest.raises(ManifestError, match="unknown module"):
        catalog().resolve(only=["ghost"])


def test_circular_requires_is_detected():
    broken = Catalog(
        modules={
            "a": module("a", requires=["b"]),
            "b": module("b", requires=["a"]),
        },
        profiles={"p": ["a"]},
    )
    with pytest.raises(ManifestError, match="circular"):
        broken.resolve("p")


def test_real_catalog_loads_and_is_consistent():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "manifests"
    loaded = load_catalog(root)

    assert "core" in loaded.modules
    assert loaded.modules["core"].always is True
    for name in loaded.profiles:
        assert loaded.resolve(name), f"profile {name} resolved to nothing"


def test_profile_referencing_missing_module_fails_at_load(tmp_path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "profiles.yaml").write_text("profiles:\n  work: [ghost]\n")
    (tmp_path / "modules" / "cli.yaml").write_text("id: cli\nname: CLI\npackages: [tree]\n")
    with pytest.raises(ManifestError, match="unknown module 'ghost'"):
        load_catalog(tmp_path)


def _adoption_catalog() -> Catalog:
    return Catalog(
        modules={
            "core": module("core", always=True),
            "cli": module("cli"),
            "terminals": module("terminals", requires=["fonts"]),
            "fonts": module("fonts"),
            "media": module("media"),
        },
        profiles={"work": ["cli", "terminals"]},
    )


def test_unadopted_reports_modules_missing_from_a_named_profile():
    catalog = _adoption_catalog()
    assert catalog.unadopted("work", ["core", "cli"]) == ["fonts", "terminals"]


def test_unadopted_spans_the_whole_catalog_for_a_custom_profile():
    # A hand-picked machine stores profile "custom", which is not a catalog
    # profile. Gating the check on a known profile name made it a silent no-op
    # there, so a module added upstream never surfaced in `status`.
    catalog = _adoption_catalog()
    assert catalog.unadopted("custom", ["core", "fonts"]) == ["cli", "media", "terminals"]


def test_unadopted_is_empty_when_everything_is_selected():
    catalog = _adoption_catalog()
    everything = ["core", "cli", "terminals", "fonts", "media"]
    assert catalog.unadopted("custom", everything) == []
    assert catalog.unadopted("work", everything) == []
