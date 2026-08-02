"""Compares live entity state against a scene's snapshot to determine
whether the scene is currently "active" - i.e. every tracked entity's
current state matches what was captured, regardless of how it got that
way (a real KNX/HA activation, or just manually setting the lights to
matching values by hand).

Rules:
- Entities with no recorded snapshot value are ignored.
- Entities currently unknown/unavailable are ignored.
- If every entity ends up ignored, the scene is considered inactive
  (off) - not unknown.
- Comparison is exact by default, except numeric attributes (brightness,
  color_temp_kelvin) may be given a small tolerance - see `tolerance`.
  This exists specifically for KNX<->HA brightness rounding: HA's
  brightness is 0-255, KNX's DPT 5.001 percentage scaling is a 0-100%
  byte, and converting through that boundary is lossy (50% can come back
  as 127 or 126 depending on rounding direction) - a strict comparator
  would flicker "inactive" on scenes that are, for all practical
  purposes, exactly right. The on/off `state` itself is always compared
  exactly regardless of tolerance - only numeric attribute *values* get
  any slack.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

IGNORED_STATES = ("unknown", "unavailable")


def _attribute_matches(current, expected, tolerance: int) -> bool:
    if isinstance(expected, (int, float)) and isinstance(current, (int, float)):
        return abs(current - expected) <= tolerance
    return current == expected


def compute_scene_active(
    hass: HomeAssistant, entities: list[str], snapshot: dict, tolerance: int = 0
) -> bool:
    if not snapshot:
        _LOGGER.debug("No snapshot recorded yet - scene considered inactive")
        return False

    compared_any = False

    for entity_id in entities:
        if entity_id not in snapshot:
            _LOGGER.debug("%s has no recorded snapshot value, ignoring", entity_id)
            continue  # nothing recorded for this entity - ignore it

        state = hass.states.get(entity_id)
        if state is None or state.state in IGNORED_STATES:
            _LOGGER.debug(
                "%s is %s, ignoring",
                entity_id,
                state.state if state is not None else "missing",
            )
            continue  # entity currently unknown/unavailable - ignore it

        compared_any = True
        expected = snapshot[entity_id]

        if isinstance(expected, dict):
            if state.state != expected.get("state"):
                _LOGGER.debug(
                    "%s state '%s' does not match snapshot state '%s' - scene inactive",
                    entity_id,
                    state.state,
                    expected.get("state"),
                )
                return False
            for attr, value in expected.items():
                if attr == "state":
                    continue
                current = state.attributes.get(attr)
                if not _attribute_matches(current, value, tolerance):
                    _LOGGER.debug(
                        "%s attribute '%s' = %s does not match snapshot value %s "
                        "(tolerance=%s) - scene inactive",
                        entity_id,
                        attr,
                        current,
                        value,
                        tolerance,
                    )
                    return False
                if current != value:
                    _LOGGER.debug(
                        "%s attribute '%s' = %s matches snapshot value %s within "
                        "tolerance %s",
                        entity_id,
                        attr,
                        current,
                        value,
                        tolerance,
                    )
            _LOGGER.debug("%s matches snapshot", entity_id)
        else:
            if state.state != expected:
                _LOGGER.debug(
                    "%s state '%s' does not match snapshot value '%s' - scene inactive",
                    entity_id,
                    state.state,
                    expected,
                )
                return False
            _LOGGER.debug("%s matches snapshot", entity_id)

    _LOGGER.debug(
        "Comparison complete: %s (compared_any=%s)",
        "active" if compared_any else "inactive",
        compared_any,
    )
    return compared_any
