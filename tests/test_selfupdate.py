from __future__ import annotations

from macsetup import selfupdate
from macsetup.runner import FakeRunner, Result


def test_upgrades_through_uv_with_a_fresh_index():
    runner = FakeRunner()
    assert selfupdate.upgrade(runner).ok
    assert runner.calls == [
        ["uv", "tool", "upgrade", "--reinstall-package", "macsetup", "macsetup"]
    ]


def test_failure_is_returned_not_raised():
    runner = FakeRunner(default=Result(2, stderr="macsetup is not installed"))
    assert selfupdate.upgrade(runner).code == 2
