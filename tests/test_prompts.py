"""The apps list widget, driven with real key presses through a pipe."""

from __future__ import annotations

from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from macsetup.prompts import Row, toggle_list

UP, DOWN, ENTER, SPACE, CTRL_C = "\x1b[A", "\x1b[B", "\r", " ", "\x03"


def drive(keys: str, rows: list[Row]):
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        with create_app_session(input=pipe, output=DummyOutput()):
            return toggle_list("q", "hint", rows, "Done", "{n}")


def rows() -> list[Row]:
    return [
        Row("Browsers"),
        Row("Chrome", "chrome", checked=True),
        Row("Dia", "dia"),
        Row("Tools"),
        Row("CLI", "cli"),
    ]


def test_enter_toggles_the_highlighted_item():
    # Down to Dia, Enter ticks it; then down past CLI to Done.
    assert drive(DOWN + ENTER + DOWN + DOWN + ENTER, rows()) == ["chrome", "dia"]


def test_enter_on_a_ticked_item_unticks_it():
    assert drive(ENTER + UP + ENTER, rows()) == []


def test_space_toggles_too():
    assert drive(DOWN + DOWN + SPACE + UP + UP + UP + ENTER, rows()) == ["chrome", "cli"]


def test_headers_are_skipped():
    # Three downs from Chrome: Dia, CLI, Done -- the "Tools" header is not a stop.
    assert drive(DOWN + DOWN + DOWN + ENTER, rows()) == ["chrome"]


def test_cursor_wraps_from_top_to_done():
    assert drive(UP + ENTER, rows()) == ["chrome"]


def test_ctrl_c_cancels():
    assert drive(CTRL_C, rows()) is None
