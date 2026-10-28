from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def example_catalog(monkeypatch):
    # The suite tests the example catalog in this checkout. A shell that has
    # macsetup set up exports these to point at a real catalog, which would
    # quietly swap it in: assertions about the example's defaults then fail,
    # and the ones that pass prove nothing about the example.
    for var in ("MACSETUP_MANIFESTS", "MACSETUP_FILES"):
        monkeypatch.delenv(var, raising=False)
