"""Shared Logbook helper.

Kept separate so scene.py, __init__.py, and button.py can all record
activity without importing each other. Every snapshot or activation -
whether triggered from the KNX side or a manual button press - logs a
distinct entry here, so it's clear at a glance what triggered what.
"""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_log_activity(hass: HomeAssistant, entity_id: str, message: str) -> None:
    """Add a Logbook entry attributed to `entity_id`. Best-effort: the
    logbook integration may not be loaded, and that should never break
    the actual scene write/activation."""
    try:
        await hass.services.async_call(
            "logbook",
            "log",
            {
                "name": "KNX Scene Sync",
                "message": message,
                "entity_id": entity_id,
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Could not write logbook entry for %s: %s", entity_id, message)
