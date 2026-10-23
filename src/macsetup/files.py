"""File steps: copy, render and managed blocks.

Deviation from plan 02, which called for symlinks: these **copy**. A symlink
into the installed package would point inside the uv tool directory and break
the next time the tool is upgraded. Copying works identically whether macsetup
runs from a repo checkout or an installed wheel, and it makes `status` able to
report a hand-edited file as drifted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from jinja2 import StrictUndefined, Template

BEGIN = "# >>> macsetup >>>"
END = "# <<< macsetup <<<"


class FileStatus(StrEnum):
    OK = "ok"
    CREATE = "create"
    UPDATE = "update"


@dataclass(frozen=True)
class Outcome:
    status: FileStatus
    dest: Path
    detail: str = ""

    @property
    def pending(self) -> bool:
        return self.status is not FileStatus.OK


def expand(path: str) -> Path:
    return Path(os.path.expandvars(path)).expanduser()


def _diff_status(dest: Path, wanted: str) -> FileStatus:
    if not dest.exists():
        return FileStatus.CREATE
    try:
        return FileStatus.OK if dest.read_text(encoding="utf-8") == wanted else FileStatus.UPDATE
    except (UnicodeDecodeError, OSError):
        return FileStatus.UPDATE


def _write(dest: Path, content: str, mode: str | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # A real file we did not write gets kept; losing a hand-made ~/.ssh config
    # to a tool run is not an acceptable failure mode.
    if dest.exists() and not dest.is_symlink():
        backup = dest.with_suffix(dest.suffix + ".macsetup-bak")
        if not backup.exists():
            backup.write_bytes(dest.read_bytes())
    dest.write_text(content, encoding="utf-8")
    if mode:
        dest.chmod(int(mode, 8))


def render_template(source: Path, variables: dict[str, str]) -> str:
    # keep_trailing_newline: jinja drops the final newline by default, which
    # leaves config files without one. StrictUndefined: a typo'd variable must
    # fail loudly rather than render as an empty string.
    template = Template(
        source.read_text(encoding="utf-8"),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    return template.render(**variables)


def plan_copy(source: Path, dest: Path) -> Outcome:
    wanted = source.read_text(encoding="utf-8")
    return Outcome(_diff_status(dest, wanted), dest)


def apply_copy(source: Path, dest: Path, mode: str | None = None) -> None:
    _write(dest, source.read_text(encoding="utf-8"), mode)


def plan_render(source: Path, dest: Path, variables: dict[str, str]) -> Outcome:
    return Outcome(_diff_status(dest, render_template(source, variables)), dest)


def apply_render(
    source: Path, dest: Path, variables: dict[str, str], mode: str | None = None
) -> None:
    _write(dest, render_template(source, variables), mode)


# --------------------------------------------------------------------------- #
# Managed blocks
#
# One marker-delimited region in a file macsetup does not own. Everything
# outside the markers is preserved untouched, so hand edits survive re-runs.


def _block_text(body: str, comment: str) -> str:
    begin = BEGIN if comment == "#" else BEGIN.replace("#", comment, 1)
    end = END if comment == "#" else END.replace("#", comment, 1)
    return f"{begin}\n{body.rstrip()}\n{end}\n"


def compose_block(existing: str, body: str, *, comment: str = "#", position: str = "bottom") -> str:
    """Return `existing` with the managed block inserted or replaced in place."""
    block = _block_text(body, comment)
    begin = block.splitlines()[0]
    end = block.splitlines()[-1]

    if begin in existing and end in existing:
        head, _, rest = existing.partition(begin)
        _, _, tail = rest.partition(end)
        return head + block.rstrip("\n") + tail

    if not existing.strip():
        return block
    if position == "top":
        # SSH cares about ordering: `Include` has to precede the Host blocks it
        # is meant to win against, so this cannot simply append.
        return block + "\n" + existing
    return existing.rstrip("\n") + "\n\n" + block


def plan_block(dest: Path, body: str, *, comment: str = "#", position: str = "bottom") -> Outcome:
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    wanted = compose_block(existing, body, comment=comment, position=position)
    if not dest.exists():
        return Outcome(FileStatus.CREATE, dest, "new file")
    if existing == wanted:
        return Outcome(FileStatus.OK, dest)
    detail = "update block" if BEGIN.replace("#", comment, 1) in existing else "insert block"
    return Outcome(FileStatus.UPDATE, dest, detail)


def apply_block(
    dest: Path, body: str, *, comment: str = "#", position: str = "bottom", mode: str | None = None
) -> None:
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        compose_block(existing, body, comment=comment, position=position), encoding="utf-8"
    )
    if mode:
        dest.chmod(int(mode, 8))
