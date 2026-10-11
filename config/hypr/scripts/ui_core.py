"""The two interface preferences (reduce motion, reduce transparency) and the policy they give the launcher and Settings, without GTK.
Standard library only. The file is `<config>/primo/ui.json`, read with config_core's rules: a missing file is the defaults (and is not
created by a read), a broken one is kept aside and the defaults are used, one from a newer Primo is never saved over.
{"version": 1, "reduce_motion": false, "reduce_transparency": false}"""
import logging
from dataclasses import dataclass
from pathlib import Path

import config_core as cc

log = logging.getLogger("primo.ui")
FLAGS = ("reduce_motion", "reduce_transparency")
_reported = set()


class UiPreferenceError(ValueError):
    """A preference that is not what it should be; the message names it."""


@dataclass(frozen=True)
class UiPreferences:
    reduce_motion: bool = False
    reduce_transparency: bool = False


@dataclass(frozen=True)
class UiPolicy:
    animate: bool       # custom transitions may run
    opaque: bool        # visible card and page content is solid


def preferences_path():
    return cc.config_home() / "primo" / "ui.json"


def parse_preferences(data):
    """UiPreferences from a table. A flag that is present must be a real boolean: "false" and 0 are refused, not read as false."""
    if not isinstance(data, dict):
        raise UiPreferenceError("the interface preferences must be a table")
    values = {}
    for flag in FLAGS:
        if flag in data:
            if not isinstance(data[flag], bool):
                raise UiPreferenceError(f"{flag} must be true or false, not {data[flag]!r}")
            values[flag] = data[flag]
    return UiPreferences(**values)


def load_preferences(path=None):
    """The saved preferences; the defaults for anything missing, broken, unreadable or newer (reported once). Never writes or creates anything
    (a file that does not parse is copied aside by config_core, as for every settings file)."""
    path = Path(path or preferences_path())
    data = cc.read_json(path, dict, {})
    try:
        return parse_preferences(data)
    except UiPreferenceError as error:
        if (path, str(error)) not in _reported:
            _reported.add((path, str(error)))
            log.warning("%s: %s; using the defaults", path, error)
        return UiPreferences()


def save_preferences(prefs, path=None):
    """Save both flags, keeping any other key of a valid file. Raises (ConfigError for a file from a newer Primo, OSError when it cannot
    be read or written) and then leaves the previous file as it was: the caller must show the failure, never claim a saved choice."""
    if not isinstance(prefs, UiPreferences):
        raise UiPreferenceError("save_preferences takes UiPreferences")
    path = Path(path or preferences_path())
    data = dict(cc.read_json(path, dict, {}))
    data.update(version=cc.SUPPORTED_VERSION, reduce_motion=prefs.reduce_motion, reduce_transparency=prefs.reduce_transparency)
    cc.write_json(path, data, 0o600)


def resolve_policy(prefs, system_animations):
    """What the windows should do. The toolkit's own animation setting always wins: off there is off here."""
    if not isinstance(system_animations, bool):
        raise UiPreferenceError("the system animation setting must be true or false")
    return UiPolicy(animate=system_animations and not prefs.reduce_motion, opaque=prefs.reduce_transparency)


PAGE_TRANSITION_MS = 180


def transition_ms(policy):
    """How long a custom page transition lasts: the usual 180 ms, none when custom animation is off."""
    return PAGE_TRANSITION_MS if policy.animate else 0
