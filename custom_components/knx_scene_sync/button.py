"""Button entities for a tracker.

Both buttons are diagnostic/maintenance actions rather than day-to-day
controls - reconfiguring a scene's stored snapshot, or forcing a KNX-side
learn, isn't something done often - so both are categorized as
EntityCategory.DIAGNOSTIC, grouping them under "Diagnostic" on the device
page rather than "Controls".

- Snapshot Entities: captures current state into the scene entity
  directly (see scene.py's async_snapshot_now). HA-side only, no KNX
  traffic. Overwrites the scene's stored values with whatever the
  tracked entities' current live state happens to be, so it's gated
  behind the same arm-then-confirm double press as KNX Learn Scene below
  - accidentally pressing it with the lights in some random state would
  silently corrupt the snapshot.
- KNX Learn Scene: sends the DPT 18.001 store telegram, gated behind an
  arm-then-confirm double press. This does NOT write the HA scene
  directly - it relies on the integration's own knx_event listener (see
  __init__.py) picking the telegram back up, exactly as it would for a
  real KNX-side learn.

  There is deliberately no separate "Activate" button here: the Scene
  entity itself (scene.py) is a real Scene entity, and Home Assistant's
  own more-info dialog for any scene already has a built-in Activate
  action - a second button doing the same thing would just be duplication.

  IMPORTANT: the Learn telegram is not scoped to Home Assistant. Any KNX
  actuator listening on this group address for this scene number will
  store its own current output as that scene's value - including devices
  that aren't part of this (or any) HA tracker.

Home Assistant has no backend mechanism for a button entity to trigger a
confirmation popup - that's a Lovelace tap_action.confirmation feature,
only available on custom dashboard cards. Instead, both buttons here use
an arm-then-confirm pattern (see ArmThenConfirmButton): the first press
arms it (name/icon change, a warning is logged) and only a second press
within ARM_SECONDS actually does anything. It disarms itself
automatically if the second press doesn't come in time.
"""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .activity import async_log_activity
from .const import (
    CONF_GROUP_ADDRESS,
    CONF_SCENE_NAME,
    CONF_SCENE_NUMBER,
    DOMAIN,
    compute_learn_payload,
    compute_scene_id,
    device_info_for_entry,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        [
            KnxSceneSnapshotButton(hass, entry),
            KnxSceneLearnButton(hass, entry),
        ]
    )


def _get_scene_entity(hass: HomeAssistant, entry: ConfigEntry):
    return hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("scene_entity")


class ArmThenConfirmButton(ButtonEntity):
    """Shared arm-then-confirm double-press logic. Subclasses set
    ARM_SECONDS / IDLE_NAME / ARMED_NAME / IDLE_ICON / ARMED_ICON /
    CONFIRM_HINT as class attributes, call self._init_arm_state() in
    their own __init__ after setting self.hass/self.entry, and implement
    _do_action() for what happens on the confirming press."""

    ARM_SECONDS = 8
    IDLE_NAME = "Confirm"
    ARMED_NAME = "Confirm (confirm)"
    IDLE_ICON = "mdi:help-circle-outline"
    ARMED_ICON = "mdi:alert-decagram"
    CONFIRM_HINT = ""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def _init_arm_state(self) -> None:
        self._attr_name = self.IDLE_NAME
        self._attr_icon = self.IDLE_ICON
        self._armed = False
        self._disarm_unsub = None

    @property
    def extra_state_attributes(self) -> dict:
        return {"armed": self._armed}

    async def async_press(self) -> None:
        if not self._armed:
            self._arm()
            return

        self._disarm(write_state=True)
        await self._do_action()

    async def _do_action(self) -> None:
        raise NotImplementedError

    @callback
    def _arm(self) -> None:
        self._armed = True
        self._attr_name = self.ARMED_NAME
        self._attr_icon = self.ARMED_ICON
        self.async_write_ha_state()
        _LOGGER.warning(
            "%s armed for '%s' - press again within %ss to confirm%s",
            self.IDLE_NAME,
            self.entry.data[CONF_SCENE_NAME],
            self.ARM_SECONDS,
            f" ({self.CONFIRM_HINT})" if self.CONFIRM_HINT else "",
        )
        self._disarm_unsub = async_call_later(self.hass, self.ARM_SECONDS, self._auto_disarm)

    @callback
    def _auto_disarm(self, _now) -> None:
        self._disarm(write_state=True)

    def _disarm(self, write_state: bool) -> None:
        self._armed = False
        self._attr_name = self.IDLE_NAME
        self._attr_icon = self.IDLE_ICON
        if self._disarm_unsub is not None:
            self._disarm_unsub()
            self._disarm_unsub = None
        if write_state:
            self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._disarm_unsub is not None:
            self._disarm_unsub()
            self._disarm_unsub = None


class KnxSceneSnapshotButton(ArmThenConfirmButton):
    """Writes the scene from current state via the scene entity itself."""

    ARM_SECONDS = 8
    IDLE_NAME = "Snapshot Entities"
    ARMED_NAME = "Snapshot Entities (confirm)"
    IDLE_ICON = "mdi:camera"
    ARMED_ICON = "mdi:alert-decagram"
    CONFIRM_HINT = "overwrites the stored snapshot with the tracked entities' current state"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_snapshot"
        self._attr_device_info = device_info_for_entry(entry)
        self._init_arm_state()

    async def _do_action(self) -> None:
        scene_entity = _get_scene_entity(self.hass, self.entry)
        if scene_entity is None:
            _LOGGER.warning(
                "Scene entity for '%s' isn't ready yet", self.entry.data[CONF_SCENE_NAME]
            )
            return
        await scene_entity.async_snapshot_now(
            log_suffix="Snapshotted to HA (manual button press)"
        )


class KnxSceneLearnButton(ArmThenConfirmButton):
    """Sends the KNX store telegram. The HA scene is updated as a side
    effect once the integration's own listener picks the telegram back
    up - this entity never writes it directly."""

    ARM_SECONDS = 8
    IDLE_NAME = "KNX Learn Scene"
    ARMED_NAME = "KNX Learn Scene (confirm)"
    IDLE_ICON = "mdi:radio-tower"
    ARMED_ICON = "mdi:alert-decagram"
    CONFIRM_HINT = (
        "overwrites the scene on every KNX device listening for it, not just entities "
        "tracked in HA"
    )

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_learn"
        self._attr_device_info = device_info_for_entry(entry)
        self._init_arm_state()

    async def _do_action(self) -> None:
        ga = self.entry.data[CONF_GROUP_ADDRESS]
        scene_number = int(self.entry.data[CONF_SCENE_NUMBER])
        await self.hass.services.async_call(
            "knx",
            "send",
            {"address": ga, "payload": [compute_learn_payload(scene_number)]},
            blocking=True,
        )

        scene_id = compute_scene_id(ga, scene_number)
        await async_log_activity(
            self.hass,
            f"scene.{scene_id}",
            f"Sent learn telegram to KNX bus for scene {scene_number} (manual button press)",
        )
