"""The tracked scene itself, owned by this integration.

Home Assistant's generic YAML-based scene platform always activates a
scene by calling services on every member entity individually - there's
no hook to change that behavior from config alone. Owning the entity
here means async_activate() can send the DPT 18.001/17.001 recall
telegram directly instead, letting the KNX actuators apply their own
bus-side stored values. This keeps HA-triggered and KNX-triggered
activation identical - whether it's this entity's own Activate action in
the UI, an automation calling scene.turn_on, or the state switch.

The "last snapshot" (captured on the most recent learn telegram, Snapshot
button press, or initial setup) lives as this entity's own
extra_state_attributes and survives restarts via Home Assistant's entity
restore mechanism (RestoreEntity, inherited from the base Scene class) -
no external file, no wrapper entity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import ExtraStoredData

from .activity import async_log_activity
from .const import (
    CONF_ENTITIES,
    CONF_GROUP_ADDRESS,
    CONF_ICON,
    CONF_SCENE_NAME,
    CONF_SCENE_NUMBER,
    CONF_SNAPSHOT_NOW,
    DOMAIN,
    SNAPSHOT_ATTRIBUTES,
    compute_recall_payload,
    compute_scene_id,
    device_info_for_entry,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class KnxSceneExtraData(ExtraStoredData):
    """Persisted alongside the entity's normal restored state.

    Restore matches by entity identity (scene.knxsync_..., derived from
    GA + scene number), not by config entry. Tagging the stored data with
    the entry_id that wrote it (owner_entry_id) means a new tracker never
    adopts another tracker's leftover snapshot just because it happens to
    reuse the same GA + scene number, while a real restart of the same
    tracker (same entry_id) still restores correctly.
    """

    snapshot: dict
    owner_entry_id: str

    def as_dict(self) -> dict:
        return {"snapshot": self.snapshot, "owner_entry_id": self.owner_entry_id}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entity = KnxSyncedScene(hass, entry)
    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})["scene_entity"] = entity
    async_add_entities([entity])


class KnxSyncedScene(Scene):
    """The tracked scene. Activating it sends a KNX recall telegram
    instead of controlling member entities individually."""

    _attr_has_entity_name = True
    _attr_name = "Scene"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        scene_id = compute_scene_id(
            entry.data[CONF_GROUP_ADDRESS], int(entry.data[CONF_SCENE_NUMBER])
        )
        self._attr_unique_id = scene_id
        # Set explicitly rather than left to auto-slugify from the name,
        # so the entity_id stays the stable knxsync_... form used
        # throughout this integration.
        self.entity_id = f"scene.{scene_id}"
        self._attr_device_info = device_info_for_entry(entry)
        self._attr_icon = entry.data.get(CONF_ICON) or None
        self._snapshot: dict = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        last_extra_data = await self.async_get_last_extra_data()
        restored_snapshot = None
        if last_extra_data is not None:
            data = last_extra_data.as_dict()
            if data.get("owner_entry_id") == self.entry.entry_id:
                restored_snapshot = data.get("snapshot", {})

        if restored_snapshot is not None:
            self._snapshot = restored_snapshot
        elif self.entry.data.get(CONF_SNAPSHOT_NOW, True):
            # First time this entity has ever existed, and the config
            # flow asked for an immediate snapshot - capture it now that
            # the entity (and therefore self.hass) actually exists.
            await self.async_snapshot_now(log_suffix="Initial snapshot on setup")

        self._notify_state_entity()

    @property
    def snapshot(self) -> dict:
        """Public read access to the current snapshot, used by the state
        entity (switch.py) for comparison. Platforms are set up
        concurrently by Home Assistant, so whichever one loads first
        tolerates the other not existing yet - each side pokes the other
        once it's ready (see _notify_state_entity and the state entity's
        own async_added_to_hass)."""
        return self._snapshot

    def _notify_state_entity(self) -> None:
        state_entity = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {}).get(
            "state_entity"
        )
        if state_entity is not None:
            state_entity.recompute_now()

    @property
    def extra_restore_state_data(self) -> ExtraStoredData:
        return KnxSceneExtraData(snapshot=self._snapshot, owner_entry_id=self.entry.entry_id)

    @property
    def extra_state_attributes(self) -> dict:
        return {"last_snapshot": self._snapshot}

    async def async_activate(self, **kwargs) -> None:
        ga = self.entry.data[CONF_GROUP_ADDRESS]
        scene_number = int(self.entry.data[CONF_SCENE_NUMBER])
        await self.hass.services.async_call(
            "knx",
            "send",
            {"address": ga, "payload": [compute_recall_payload(scene_number)]},
            blocking=True,
        )
        await async_log_activity(
            self.hass, self.entity_id, f"Activated on KNX bus (scene {scene_number})"
        )

    async def async_snapshot_now(self, log_suffix: str = "Snapshotted") -> None:
        """Capture current state of the tracked entities into this scene."""
        entities = self.entry.data[CONF_ENTITIES]
        values: dict = {}
        for entity_id in entities:
            state = self.hass.states.get(entity_id)
            if state is None:
                _LOGGER.warning(
                    "Entity %s has no current state, skipping in scene snapshot",
                    entity_id,
                )
                continue
            value: dict = {"state": state.state}
            for attr in SNAPSHOT_ATTRIBUTES:
                if attr in state.attributes:
                    value[attr] = state.attributes[attr]
            values[entity_id] = value if len(value) > 1 else state.state

        self._snapshot = values
        self.async_write_ha_state()
        await async_log_activity(self.hass, self.entity_id, log_suffix)
        # A fresh snapshot changes what "matching" means - re-evaluate the
        # state entity immediately (not debounced) rather than waiting for
        # a member's state_changed event, since the snapshot itself just
        # changed, not necessarily any entity's live state.
        self._notify_state_entity()
