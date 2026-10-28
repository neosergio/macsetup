"""Manifest loading and validation.

Manifests are the source of truth: adding a package should be a data edit, not
a code change. Pydantic catches a typo'd key at load time rather than halfway
through an install.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ALL = "*"


class ManifestError(RuntimeError):
    pass


class Package(BaseModel):
    """One installable. Accepts shorthand: `- git` or `- {name: arc, cask: true}`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    cask: bool = False
    mas: int | None = None
    # What the wizard shows. Homebrew tokens are not always the name people
    # know an app by -- Dia is `thebrowsercompany-dia`.
    title: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, value: Any) -> Any:
        return {"name": value} if isinstance(value, str) else value

    @property
    def label(self) -> str:
        return self.title or self.name

    def brewfile_line(self) -> str:
        if self.mas is not None:
            return f'mas "{self.name}", id: {self.mas}'
        verb = "cask" if self.cask else "brew"
        return f'{verb} "{self.name}"'


class FileSpec(BaseModel):
    """One file action. Exactly one of copy/render/block names the source.

    copy   -- verbatim, e.g. a zsh fragment
    render -- Jinja2 with machine vars, e.g. the ssh config
    block  -- marker-delimited region inside a file macsetup does not own
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    # `copy_` is aliased because a field literally named `copy` shadows
    # BaseModel.copy; the manifest key stays `copy:`.
    copy_: str | None = Field(default=None, alias="copy")
    render: str | None = None
    block: str | None = None
    to: str | None = None
    into: str | None = None
    mode: str | None = None
    comment: str = "#"
    position: Literal["top", "bottom"] = "bottom"

    _FIELDS = {"copy": "copy_", "render": "render", "block": "block"}

    @model_validator(mode="after")
    def _check(self) -> FileSpec:
        kinds = [k for k, f in self._FIELDS.items() if getattr(self, f)]
        if len(kinds) != 1:
            raise ValueError(f"need exactly one of copy/render/block, got {kinds or 'none'}")
        if self.kind == "block":
            if not self.into:
                raise ValueError("`block` needs `into:` (the file to edit)")
            if self.to:
                raise ValueError("`block` uses `into:`, not `to:`")
        else:
            if not self.to:
                raise ValueError(f"`{self.kind}` needs `to:` (the destination path)")
            if self.into:
                raise ValueError(f"`{self.kind}` uses `to:`, not `into:`")
        if self.mode:
            try:
                int(self.mode, 8)
            except ValueError:
                raise ValueError(f'mode {self.mode!r} is not octal, e.g. "600"') from None
        return self

    @property
    def kind(self) -> str:
        for kind, field_name in self._FIELDS.items():
            if getattr(self, field_name):
                return kind
        raise AssertionError("validated above")

    @property
    def source(self) -> str:
        return getattr(self, self._FIELDS[self.kind])

    @property
    def target(self) -> str:
        return self.into if self.kind == "block" else self.to  # type: ignore[return-value]


class Module(BaseModel):
    """A unit of setup, and the thing the wizard offers as a choice.

    `select: pick` means the wizard offers per-package checkboxes instead of
    treating the module as atomic -- for genuine menus like editors, where
    wanting half the module is normal.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str = ""
    always: bool = False
    select: Literal["all", "pick"] = "all"
    default: list[str] = Field(default_factory=list)
    requires: list[str] = Field(default_factory=list)
    packages: list[Package] = Field(default_factory=list)
    files: list[FileSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Module:
        names = {p.name for p in self.packages}
        unknown = [d for d in self.default if d not in names]
        if unknown:
            raise ValueError(f"module {self.id!r}: default lists unknown packages {unknown}")
        if self.select == "all" and self.default:
            raise ValueError(f"module {self.id!r}: `default` only applies when select: pick")
        return self

    def selected_packages(self, picks: set[str] | None = None) -> list[Package]:
        """Packages to install, honouring per-package picks for `select: pick`."""
        if self.select == "all":
            return list(self.packages)
        chosen = picks if picks is not None else set(self.default)
        return [p for p in self.packages if p.name in chosen]


class Catalog(BaseModel):
    modules: dict[str, Module]
    profiles: dict[str, list[str]]

    def module(self, module_id: str) -> Module:
        try:
            return self.modules[module_id]
        except KeyError:
            raise ManifestError(f"unknown module {module_id!r}") from None

    def resolve(
        self,
        profile: str | None = None,
        only: list[str] | None = None,
        *,
        include_always: bool | None = None,
    ) -> list[Module]:
        """Profile (or explicit module list) -> ordered, dependency-closed modules.

        `always` modules are folded in unconditionally; `--only` is the one case
        where that is skipped, since it means "just this, I know what I want".
        Applying a saved machine selection overrides that with
        include_always=True, since machine.toml stores optional modules only.

        An *empty* `only` is a selection, not the absence of one: a machine.toml
        with `modules = []` resolves to the always-on modules and nothing else.
        Falling back to the profile there would report "need a profile" on a
        machine that is configured and names its profile in the file.
        """
        if only is not None:
            wanted = list(only)
            include_always = False if include_always is None else include_always
        else:
            if profile is None:
                raise ManifestError("need a profile or an explicit module list")
            if profile not in self.profiles:
                known = ", ".join(sorted(self.profiles))
                raise ManifestError(f"unknown profile {profile!r} (have: {known})")
            entries = self.profiles[profile]
            wanted = list(self.modules) if ALL in entries else list(entries)
            include_always = True if include_always is None else include_always

        for module_id in wanted:
            self.module(module_id)

        seen: set[str] = set()
        ordered: list[str] = []

        def visit(module_id: str, trail: tuple[str, ...] = ()) -> None:
            if module_id in seen:
                return
            if module_id in trail:
                cycle = " -> ".join([*trail, module_id])
                raise ManifestError(f"circular requires: {cycle}")
            for dep in self.module(module_id).requires:
                visit(dep, (*trail, module_id))
            seen.add(module_id)
            ordered.append(module_id)

        if include_always:
            for module_id, module in self.modules.items():
                if module.always:
                    visit(module_id)
        for module_id in wanted:
            visit(module_id)

        return [self.modules[m] for m in ordered]

    def unadopted(self, profile: str, selected: Iterable[str]) -> list[str]:
        """Modules this machine could adopt but has not.

        A hand-picked machine stores profile "custom", which is not a catalog
        profile, and `state.py` falls back to the same string when the key is
        missing. Treating an unknown profile as "the whole catalog" is what
        keeps this check alive there -- gating it on a known profile name
        disabled it on exactly the machines most likely to lag behind upstream.
        """
        candidates = (
            {m.id for m in self.resolve(profile)} if profile in self.profiles else set(self.modules)
        )
        return sorted(candidates - set(selected))


def _resolve_dir(env_var: str, name: str, sentinel: str) -> Path:
    """Locate a data dir: env override, then repo checkout, then packaged copy."""
    override = os.environ.get(env_var)
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise ManifestError(f"{env_var} points at {path}, which is not a directory")
        return path

    repo = Path.cwd() / name
    if (repo / sentinel).exists():
        return repo

    packaged = Path(__file__).parent / "_data" / name
    if (packaged / sentinel).exists():
        return packaged

    raise ManifestError(f"no {name}/ found; set {env_var} or run from the repo root")


def manifests_dir() -> Path:
    return _resolve_dir("MACSETUP_MANIFESTS", "manifests", "profiles.yaml")


def files_dir() -> Path:
    """Where `copy:`/`render:`/`block:` sources are resolved from."""
    return _resolve_dir("MACSETUP_FILES", "files", "zsh")


def catalog_vars(root: Path | None = None) -> dict[str, str]:
    """Default `render:` variables, declared by the catalog in vars.yaml.

    Who you are is data, not code: the engine ships no name or email of its
    own, so the same engine serves a public catalog and a private one. A
    machine overrides individual values in the [vars] table of machine.toml.

    Rendering uses StrictUndefined, so every variable a template references
    must have a value here or in machine.toml -- a missing one is a hard error
    rather than a silently empty `email = ` in a config file.
    """
    path = (root or manifests_dir()) / "vars.yaml"
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict) or not isinstance(loaded.get("vars", {}), dict):
        raise ManifestError(f"{path} must hold a `vars:` mapping of names to values")
    return {str(k): str(v) for k, v in (loaded.get("vars") or {}).items()}


def load_catalog(root: Path | None = None) -> Catalog:
    root = root or manifests_dir()

    profiles_file = root / "profiles.yaml"
    if not profiles_file.is_file():
        raise ManifestError(f"missing {profiles_file}")
    profiles_doc = _read_yaml(profiles_file)
    profiles = profiles_doc.get("profiles")
    if not isinstance(profiles, dict):
        raise ManifestError(f"{profiles_file}: expected a top-level `profiles:` mapping")

    modules: dict[str, Module] = {}
    for path in sorted((root / "modules").glob("*.yaml")):
        try:
            module = Module.model_validate(_read_yaml(path))
        except Exception as exc:
            raise ManifestError(f"{path.name}: {exc}") from exc
        if module.id in modules:
            raise ManifestError(f"{path.name}: duplicate module id {module.id!r}")
        modules[module.id] = module

    if not modules:
        raise ManifestError(f"no module manifests found in {root / 'modules'}")

    catalog = Catalog(modules=modules, profiles=profiles)

    # Fail at load time rather than when someone selects the broken profile.
    for name, entries in profiles.items():
        for module_id in entries:
            if module_id != ALL and module_id not in modules:
                raise ManifestError(f"profile {name!r} references unknown module {module_id!r}")
    for module in modules.values():
        for dep in module.requires:
            if dep not in modules:
                raise ManifestError(f"module {module.id!r} requires unknown module {dep!r}")

    return catalog


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: expected a YAML mapping")
    return data
