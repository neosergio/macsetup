from __future__ import annotations

import pytest

from macsetup import i18n
from macsetup.runner import FakeRunner, Result

APPLE = "defaults read -g AppleLanguages"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("MACSETUP_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)


def runner(apple: str | None) -> FakeRunner:
    if apple is None:
        return FakeRunner(default=Result(1))
    return FakeRunner(responses={APPLE: Result(0, apple)})


def test_override_wins(monkeypatch):
    monkeypatch.setenv("MACSETUP_LANG", "es")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.detect(runner('(\n    "en-US"\n)')) == "es"


def test_unsupported_override_means_english(monkeypatch):
    monkeypatch.setenv("MACSETUP_LANG", "fr")
    assert i18n.detect(runner('(\n    "es-PE"\n)')) == "en"


def test_spanish_locale(monkeypatch):
    monkeypatch.setenv("LANG", "es_PE.UTF-8")
    assert i18n.detect(runner(None)) == "es"


def test_english_locale_defers_to_macos(monkeypatch):
    # en_US is what an unconfigured terminal reports, not necessarily a choice.
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.detect(runner('(\n    "es-419",\n    "en-US"\n)')) == "es"


def test_macos_first_supported_language(monkeypatch):
    assert i18n.detect(runner('(\n    "fr-FR",\n    "es-ES"\n)')) == "es"


def test_default_is_english():
    assert i18n.detect(runner(None)) == "en"


def test_both_languages_have_the_same_keys():
    assert set(i18n.MESSAGES["es"]) == set(i18n.MESSAGES["en"])
