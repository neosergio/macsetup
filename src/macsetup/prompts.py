"""A checklist where Enter toggles and a last entry confirms.

questionary's checkbox ticks with space and submits with Enter, and pressing
Enter on the item you meant to tick -- submitting the list without it -- is
the most common way people get that prompt wrong. Here Enter on an item
toggles it (space does too), and only Enter on the final entry returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style


@dataclass
class Row:
    """One line of the list. A row without a value is a group header."""

    label: str
    value: Any = None
    checked: bool = False
    note: str = ""
    # Shown instead of `note`, as a warning, while the row is unticked. It
    # follows the tick live: unticking an installed app flags it on the spot.
    note_off: str = ""


_STYLE = Style.from_dict(
    {
        "question": "bold",
        "hint": "#888888",
        "header": "#888888 bold",
        "checked": "fg:ansigreen",
        "pointed": "fg:ansicyan bold",
        "note": "#888888",
        "warn": "fg:ansiyellow",
        "done": "bold",
        "answer": "fg:ansicyan",
    }
)


def toggle_list(message: str, hint: str, rows: list[Row], done: str, summary: str) -> list | None:
    """Show the list; return the ticked values in row order, or None if cancelled.

    `summary` is printed after the answer in place of the list, with `{n}`
    replaced by the number of ticked rows.
    """
    items = [i for i, row in enumerate(rows) if row.value is not None]
    checked = {i for i in items if rows[i].checked}
    stops = [*items, len(rows)]  # len(rows) is the Done entry
    state = {"at": 0}

    def fragments() -> list[tuple[str, str]]:
        here = stops[state["at"]]
        out = [("class:question", f"? {message}\n"), ("class:hint", f"  {hint}\n")]
        for i, row in enumerate(rows):
            if row.value is None:
                out.append(("class:header", f"\n  {row.label}\n"))
                continue
            style = "class:pointed" if i == here else ("class:checked" if i in checked else "")
            if i == here:
                # Lets the window scroll to keep the pointer visible.
                out.append(("[SetCursorPosition]", ""))
            box = "✔" if i in checked else "☐"
            out.append((style, f"{'❯' if i == here else ' '} {box} {row.label}"))
            if row.note_off and i not in checked:
                out.append(("class:warn", f"  {row.note_off}"))
            elif row.note:
                out.append(("class:note", f"  {row.note}"))
            out.append(("", "\n"))
        is_done = here == len(rows)
        out.append(("", "\n"))
        if is_done:
            # After the blank line, not before it: the window scrolls to the
            # cursor's line, and Done must be on screen when it is the target.
            out.append(("[SetCursorPosition]", ""))
        out.append(
            ("class:pointed" if is_done else "class:done", f"{'❯' if is_done else ' '} ✓ {done}")
        )
        return out

    keys = KeyBindings()

    @keys.add("up")
    @keys.add("k")
    def _up(event) -> None:
        state["at"] = (state["at"] - 1) % len(stops)

    @keys.add("down")
    @keys.add("j")
    def _down(event) -> None:
        state["at"] = (state["at"] + 1) % len(stops)

    @keys.add("enter")
    @keys.add("space")
    def _toggle(event) -> None:
        here = stops[state["at"]]
        if here == len(rows):
            event.app.exit(result=[rows[i].value for i in items if i in checked])
        else:
            checked.symmetric_difference_update({here})

    # Ctrl-C only, as in questionary. Escape is not bound: arrow keys arrive as
    # escape sequences, and a split one would cancel the whole wizard.
    @keys.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result=None)

    control = FormattedTextControl(fragments, focusable=True, show_cursor=False)
    app: Application = Application(
        layout=Layout(HSplit([Window(control, wrap_lines=True)])),
        key_bindings=keys,
        style=_STYLE,
        erase_when_done=True,
    )
    result = app.run()
    if result is not None:
        print_formatted_text(
            FormattedText(
                [
                    ("class:question", f"? {message} "),
                    ("class:answer", summary.format(n=len(result))),
                ]
            ),
            style=_STYLE,
        )
    return result
