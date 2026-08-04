"""KNX Scene Sync.

Owns its scene entities directly (see scene.py) instead of relying on
Home Assistant's generic YAML-based scene platform. Since entities now
live and die with their config entry, there's no external file to keep in
sync and no orphan-cleanup logic needed anymore - Home Assistant already
guarantees an entity only exists while its entry is loaded.

Learning (storing) works for DPT 18.001 trackers: a store telegram -
whether a real KNX-side learn, or this integration's own Learn button
looping its telegram back - is picked up by the listener below and
turned into a snapshot on the matching scene entity. DPT 17.001 trackers
have no control bit at all, so every telegram on the GA is unambiguously
a recall - the listener still matches and logs it (useful feedback that
the scene was recalled from the KNX side), but never snapshots.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .activity import async_log_activity
from .const import (
    CONF_GA_TYPE,
    CONF_GROUP_ADDRESS,
    CONF_SCENE_NAME,
    CONF_SCENE_NUMBER,
    DOMAIN,
    GA_TYPE_DPT18,
    compute_scene_id,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button", "scene", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ga = entry.data[CONF_GROUP_ADDRESS]
    ga_type = entry.data.get(CONF_GA_TYPE, GA_TYPE_DPT18)
    scene_number = int(entry.data[CONF_SCENE_NUMBER])
    scene_id = compute_scene_id(ga, scene_number)

    # "dependencies": ["knx"] in manifest.json only guarantees the KNX
    # component's code has loaded first - it does not wait for KNX's own
    # config entry to finish connecting. If the KNX interface is offline
    # at startup, KNX's entry can still be mid-connect (or itself
    # retrying) when this runs, in which case hass.data["knx"] doesn't
    # exist yet and this call raises. Catching that and raising
    # ConfigEntryNotReady tells Home Assistant to retry this entry
    # automatically with backoff, instead of leaving it in a failed
    # state that only a manual reload would recover from.
    try:
        await hass.services.async_call(
            "knx", "event_register", {"address": [ga]}, blocking=True
        )
    except Exception as err:
        raise ConfigEntryNotReady(
            f"KNX integration not ready yet for group address {ga}"
        ) from err

    @callback
    def _handle_knx_event(event: Event) -> None:
        """DPT 18.001: snapshots the tracked scene on any matching learn
        telegram - whether it originated from KNX itself or from this
        entry's Learn button sending the same store telegram (see
        button.py). DPT 17.001: every telegram is a recall (no control
        bit exists to check) - matched telegrams are logged, never
        snapshotted."""
        if event.data.get("destination") != ga:
            return

        raw = event.data.get("data")
        byte = raw[0] if isinstance(raw, (list, tuple)) else raw
        if byte is None:
            return

        _LOGGER.debug("Telegram on %s (tracker for scene %s): raw data=%s", ga, scene_number, byte)

        if ga_type != GA_TYPE_DPT18:
            # DPT 17.001 has no control bit at all - the full byte (0-63)
            # is just the scene number, and every telegram is a recall.
            recalled_number = (byte % 64) + 1
            if recalled_number != scene_number:
                return
            _LOGGER.debug("Recall telegram matched %s scene %s (DPT 17.001)", ga, scene_number)
            hass.async_create_task(
                async_log_activity(
                    hass,
                    f"scene.{scene_id}",
                    f"Recalled from KNX bus (scene {scene_number})",
                )
            )
            return

        if byte < 128:
            _LOGGER.debug("Not a learn telegram (control bit not set), ignoring")
            return

        learned_number = (byte % 64) + 1
        if learned_number != scene_number:
            _LOGGER.debug(
                "Learn telegram was for scene %s, this tracker watches scene %s, ignoring",
                learned_number,
                scene_number,
            )
            return

        _LOGGER.debug("Learn telegram matched %s scene %s", ga, scene_number)

        scene_entity = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("scene_entity")
        if scene_entity is None:
            _LOGGER.warning(
                "Learn telegram matched but scene entity for '%s' isn't ready yet",
                entry.data[CONF_SCENE_NAME],
            )
            return

        hass.async_create_task(
            async_log_activity(
                hass,
                f"scene.{scene_id}",
                f"Received learn telegram for scene {scene_number} on {ga}",
            )
        )
        hass.async_create_task(scene_entity.async_snapshot_now())

    entry.async_on_unload(hass.bus.async_listen("knx_event", _handle_knx_event))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded
