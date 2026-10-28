"""The wizard's words, in English and Spanish.

Only the interactive parts are translated -- the wizard and the lines around
it. Plan tables and errors stay English: they are what people paste into
issues, and one language there keeps them searchable.
"""

from __future__ import annotations

import os

from .runner import Runner

SUPPORTED = ("en", "es")

MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "name": "Name this machine",
        "purpose": "What is this Mac for?",
        "purpose_hint": "A starting point: it only pre-ticks apps, which you choose next.",
        "custom": "start empty, I'll choose",
        "groups": "{n} groups",
        "group": "1 group",
        "everything": "everything",
        "back": "← back",
        "apps": "What should this Mac have?",
        "apps_hint": "↑↓ move · Enter ticks/unticks · choose “Done” to continue",
        "done": "Done",
        "tools": "Tools",
        "installed": "(installed)",
        "always": "Always included: {names}",
        "review": "Review",
        "machine": "machine",
        "apps_label": "apps",
        "nothing": "(nothing)",
        "required": "also installed, required by your choice: {names}",
        "save": "Save",
        "change_name": "← change machine name",
        "change_apps": "← change apps",
        "change_purpose": "← start from another suggestion",
        "ticked": "{n} ticked",
        "needs_tty": "The wizard needs an interactive terminal.",
        "needs_tty_hint": "Non-interactively, every answer has a flag:",
        "cancelled": "Cancelled. Nothing was saved.",
        "no_terminal": "Could not read from the terminal:",
        "empty_confirm": "Nothing selected — only the always-on modules would apply. Save that?",
        "already": "This machine is already configured as {machine}; "
        "your current choices are pre-ticked.",
        "saved": "Saved {path}",
        "run_apply": "Run macsetup apply to install.",
        "run_apply_later": "Run macsetup apply when ready.",
    },
    "es": {
        "name": "Nombre de esta Mac",
        "purpose": "¿Para qué es esta Mac?",
        "purpose_hint": "Es un punto de partida: solo pre-marca apps, que eliges después.",
        "custom": "empezar vacío, elijo yo",
        "groups": "{n} grupos",
        "group": "1 grupo",
        "everything": "todo",
        "back": "← volver",
        "apps": "¿Qué debe tener esta Mac?",
        "apps_hint": "↑↓ moverse · Enter marca/desmarca · elige “Listo” para seguir",
        "done": "Listo",
        "tools": "Herramientas",
        "installed": "(instalado)",
        "always": "Siempre incluido: {names}",
        "review": "Revisión",
        "machine": "mac",
        "apps_label": "apps",
        "nothing": "(nada)",
        "required": "también se instala, lo requiere tu elección: {names}",
        "save": "Guardar",
        "change_name": "← cambiar el nombre",
        "change_apps": "← cambiar las apps",
        "change_purpose": "← empezar desde otra sugerencia",
        "ticked": "{n} marcados",
        "needs_tty": "El asistente necesita una terminal interactiva.",
        "needs_tty_hint": "Sin terminal, cada respuesta tiene su opción:",
        "cancelled": "Cancelado. No se guardó nada.",
        "no_terminal": "No se pudo leer la terminal:",
        "empty_confirm": "No marcaste nada: solo se aplicarían los módulos fijos. ¿Guardar así?",
        "already": "Esta Mac ya está configurada como {machine}; "
        "tus elecciones actuales vienen marcadas.",
        "saved": "Guardado en {path}",
        "run_apply": "Ejecuta macsetup apply para instalar.",
        "run_apply_later": "Ejecuta macsetup apply cuando quieras.",
    },
}


def _from_locale(value: str | None) -> str | None:
    """'es_PE.UTF-8' -> 'es'; 'C', 'POSIX' and unknown languages -> None."""
    if not value:
        return None
    code = value.split(".")[0].replace("-", "_").split("_")[0].lower()
    return code if code in SUPPORTED else None


def detect(runner: Runner) -> str:
    """MACSETUP_LANG, then the locale variables, then macOS's language list.

    Terminal.app sets LANG from the system region by default, but other
    terminals often leave it at en_US or unset, so the macOS preference is
    the fallback that matches what the person actually reads.
    """
    override = os.environ.get("MACSETUP_LANG")
    if override:
        return _from_locale(override) or "en"
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        lang = _from_locale(os.environ.get(var))
        # en_US is also what an unconfigured terminal says, so English from
        # the locale is not taken as a choice; the macOS setting decides.
        if lang and lang != "en":
            return lang
    result = runner.run(["defaults", "read", "-g", "AppleLanguages"])
    if result.ok:
        for line in result.lines():
            lang = _from_locale(line.strip(' ",()'))
            if lang:
                return lang
    return "en"


def messages(lang: str) -> dict[str, str]:
    return MESSAGES.get(lang, MESSAGES["en"])
