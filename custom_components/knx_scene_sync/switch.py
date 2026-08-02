"""The scene's state entity - a switch, always created for every tracker.

Being a switch means it's controllable, which is what's needed for it to
appear as a toggleable accessory when exposed through Home Assistant's
HomeKit Bridge:
- Turning it on activates the scene, via the same scene.turn_on path as
  the scene entity's own Activate action - not a separate implementation
  to drift out of sync.
- Turning it off runs whichever "Off action" is configured for this
  tracker: no action, activating another scene (any scene, not just one
  tracked by this integration - typically a matching "off" tracker), or
  turning off every tracked entity directly. See async_turn_off.

Also responsible for:
- Recomputing "is the scene currently active" via comparator.py whenever
  a tracked entity's state changes, or whenever the scene captures a new
  snapshot (see scene.py's _notify_state_entity).
- Debouncing those recomputes: a scene activation typically causes
  several member entities to change state in quick succession as they
  settle (dimming ramps, sequential bus telegrams) - recomputing on every
  single one would flicker through intermediate states. Rapid changes are
  coalesced into one recompute after the configured debounce time of
  quiet (CONF_DEBOUNCE_SECONDS, per-tracker; DEBOUNCE_SECONDS below is
  only the fallback for trackers created before this was configurable).
- Registering/unregistering a KNX status exposure (knx.exposure_register)
  if a state group address is configured, so other KNX devices can read
  this scene's active/inactive status directly from the bus.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .comparator import compute_scene_active
from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_ENTITIES,
    CONF_GROUP_ADDRESS,
    CONF_NUMERIC_TOLERANCE,
    CONF_OFF_ACTION,
    CONF_OFF_SCENE_ENTITY,
    CONF_SCENE_NAME,
    CONF_SCENE_NUMBER,
    CONF_STATE_GROUP_ADDRESS,
    DOMAIN,
    OFF_ACTION_ACTIVATE_SCENE,
    OFF_ACTION_NONE,
    OFF_ACTION_TURN_OFF,
    compute_scene_id,
    device_info_for_entry,
)

_LOGGER = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 1.5


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([KnxSceneStateSwitch(hass, entry)])


class KnxSceneStateSwitch(SwitchEntity):
    """Tracks whether the scene is currently active, and can activate/
    deactivate it."""

    _attr_has_entity_name = True
    _attr_name = "State"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_state"
        self._attr_device_info = device_info_for_entry(entry)
        self._attr_is_on = False
        self._debounce_unsub = None

    async def async_added_to_hass(self) -> None:
        self.hass.data.setdefault(DOMAIN, {}).setdefault(self.entry.entry_id, {})[
            "state_entity"
        ] = self

        tracked_entities = self.entry.data[CONF_ENTITIES]
        if tracked_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, tracked_entities, self._handle_member_change
                )
            )

        await self._async_register_expose()

        # Best-effort initial value - the scene entity may not have
        # finished its own setup yet (platforms load concurrently), in
        # which case this reads an empty snapshot (-> off) and gets
        # corrected shortly after via the scene entity's own
        # _notify_state_entity call once it's ready.
        self.recompute_now()

    async def async_will_remove_from_hass(self) -> None:
        if self._debounce_unsub is not None:
            self._debounce_unsub()
            self._debounce_unsub = None
        await self._async_unregister_expose()

    @callback
    def _handle_member_change(self, event: Event) -> None:
        entity_id = event.data.get("entity_id")
        debounce_seconds = float(self.entry.data.get(CONF_DEBOUNCE_SECONDS, DEBOUNCE_SECONDS))
        _LOGGER.debug(
            "%s changed, (re)scheduling debounced recompute for %s in %ss",
            entity_id,
            self.entity_id,
            debounce_seconds,
        )
        if self._debounce_unsub is not None:
            self._debounce_unsub()
        self._debounce_unsub = async_call_later(
            self.hass, debounce_seconds, self._debounced_recompute
        )

    @callback
    def _debounced_recompute(self, _now) -> None:
        self._debounce_unsub = None
        _LOGGER.debug("Debounce elapsed for %s, recomputing", self.entity_id)
        self.recompute_now()

    @callback
    def recompute_now(self) -> None:
        """Recompute immediately, bypassing debounce. Called on setup, and
        by the scene entity right after a new snapshot is captured (the
        comparison baseline changed, not necessarily any live entity
        state, so there's nothing to debounce)."""
        scene_entity = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {}).get(
            "scene_entity"
        )
        snapshot = scene_entity.snapshot if scene_entity is not None else {}
        tolerance = int(self.entry.data.get(CONF_NUMERIC_TOLERANCE, 1))
        _LOGGER.debug(
            "Recomputing state for %s against %d tracked entities, %d snapshot entries "
            "(tolerance=%s)",
            self.entity_id,
            len(self.entry.data[CONF_ENTITIES]),
            len(snapshot),
            tolerance,
        )
        new_value = compute_scene_active(
            self.hass, self.entry.data[CONF_ENTITIES], snapshot, tolerance
        )

        if new_value != self._attr_is_on:
            _LOGGER.debug(
                "%s changing state: %s -> %s", self.entity_id, self._attr_is_on, new_value
            )
            self._attr_is_on = new_value
            if self.hass is not None and self.entity_id:
                self.async_write_ha_state()
        else:
            _LOGGER.debug("%s state unchanged: %s", self.entity_id, new_value)

    async def async_turn_on(self, **kwargs) -> None:
        scene_id = compute_scene_id(
            self.entry.data[CONF_GROUP_ADDRESS], int(self.entry.data[CONF_SCENE_NUMBER])
        )
        await self.hass.services.async_call(
            "scene", "turn_on", {"entity_id": f"scene.{scene_id}"}, blocking=True
        )

    async def async_turn_off(self, **kwargs) -> None:
        # Deliberately different from the config flow's default for a
        # brand-new tracker (which is now "No action"): this fallback is
        # specifically for trackers created before this setting existed
        # at all, whose entry.data has no off_action key - falling back
        # to the original fixed behavior (turn off every tracked entity)
        # so upgrading never silently changes what those existing
        # trackers do.
        off_action = self.entry.data.get(CONF_OFF_ACTION, OFF_ACTION_TURN_OFF)

        if off_action == OFF_ACTION_NONE:
            return

        if off_action == OFF_ACTION_ACTIVATE_SCENE:
            target = self.entry.data.get(CONF_OFF_SCENE_ENTITY)
            if not target:
                _LOGGER.warning(
                    "Off action for '%s' is set to activate another scene, "
                    "but none is configured - doing nothing",
                    self.entry.data[CONF_SCENE_NAME],
                )
                return
            await self.hass.services.async_call(
                "scene", "turn_on", {"entity_id": target}, blocking=True
            )
            return

        # OFF_ACTION_TURN_OFF
        entities = self.entry.data[CONF_ENTITIES]
        if entities:
            await self.hass.services.async_call(
                "homeassistant", "turn_off", {"entity_id": entities}, blocking=True
            )

    async def _async_register_expose(self) -> None:
        address = self.entry.data.get(CONF_STATE_GROUP_ADDRESS)
        if not address:
            return
        try:
            await self.hass.services.async_call(
                "knx",
                "exposure_register",
                {
                    "address": address,
                    "type": "binary",
                    "entity_id": self.entity_id,
                    "default": "off",
                },
                blocking=True,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Could not register KNX status exposure on %s for %s", address, self.entity_id
            )

    async def _async_unregister_expose(self) -> None:
        address = self.entry.data.get(CONF_STATE_GROUP_ADDRESS)
        if not address:
            return
        try:
            await self.hass.services.async_call(
                "knx", "exposure_register", {"address": address, "remove": True}, blocking=True
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not remove KNX status exposure on %s", address)
