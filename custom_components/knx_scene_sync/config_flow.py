"""Config flow for KNX Scene Sync.

Each flow (Add, Edit, Duplicate) is split into two steps: tracker basics
first (name, GA, scene number, entities), then a separate page for the
state switch settings (status GA, off action, tolerance, debounce).
Each step is its own async_show_form call with its own title.

Field labels, error messages, and step titles rely on standard Home
Assistant translation resolution (strings.json / translations/*.json).
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector

from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_ENTITIES,
    CONF_GA_TYPE,
    CONF_GROUP_ADDRESS,
    CONF_NUMERIC_TOLERANCE,
    CONF_OFF_ACTION,
    CONF_OFF_SCENE_ENTITY,
    CONF_SCENE_NAME,
    CONF_SCENE_NUMBER,
    CONF_SNAPSHOT_NOW,
    CONF_STATE_GROUP_ADDRESS,
    DOMAIN,
    GA_RE,
    GA_TYPE_DPT17,
    GA_TYPE_DPT18,
    OFF_ACTION_ACTIVATE_SCENE,
    OFF_ACTION_NONE,
    OFF_ACTION_TURN_OFF,
    compute_scene_id,
)

# ---------------------------------------------------------------------------
# Schema builders
# ---------------------------------------------------------------------------


def _tracker_schema(defaults: dict | None = None) -> vol.Schema:
    defaults = defaults or {}

    fields: dict = {
        vol.Required(
            CONF_SCENE_NAME, default=defaults.get(CONF_SCENE_NAME, "")
        ): selector.TextSelector(),
        vol.Required(
            CONF_GROUP_ADDRESS, default=defaults.get(CONF_GROUP_ADDRESS, "")
        ): selector.TextSelector(),
        vol.Required(
            CONF_GA_TYPE, default=defaults.get(CONF_GA_TYPE, GA_TYPE_DPT18)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=selector.SelectSelectorMode.LIST,
                options=[
                    selector.SelectOptionDict(
                        value=GA_TYPE_DPT18, label="DPT 18.001 (recall + learn)"
                    ),
                    selector.SelectOptionDict(
                        value=GA_TYPE_DPT17, label="DPT 17.001 (recall only)"
                    ),
                ],
            )
        ),
        # Always give NumberSelector a real default (never an unset
        # field) - callers that want a fresh, non-colliding suggestion
        # (Duplicate) compute one explicitly, see
        # _next_available_scene_number.
        vol.Required(
            CONF_SCENE_NUMBER, default=defaults.get(CONF_SCENE_NUMBER, 1)
        ): selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=64, mode="box")),
        # Restricted to entities provided by the KNX integration - these
        # are the only ones that make sense for a KNX-backed scene, and it
        # keeps the picker from being cluttered with unrelated entities.
        vol.Required(
            CONF_ENTITIES, default=defaults.get(CONF_ENTITIES, [])
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=True, integration="knx")
        ),
    }
    return vol.Schema(fields)


def _state_schema(defaults: dict | None = None, include_snapshot: bool = False) -> vol.Schema:
    defaults = defaults or {}

    fields: dict = {
        vol.Optional(
            CONF_STATE_GROUP_ADDRESS, default=defaults.get(CONF_STATE_GROUP_ADDRESS, "")
        ): selector.TextSelector(),
        vol.Required(
            CONF_OFF_ACTION, default=defaults.get(CONF_OFF_ACTION, OFF_ACTION_NONE)
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=selector.SelectSelectorMode.LIST,
                options=[
                    selector.SelectOptionDict(value=OFF_ACTION_NONE, label="No action"),
                    selector.SelectOptionDict(
                        value=OFF_ACTION_ACTIVATE_SCENE, label="Activate another scene"
                    ),
                    selector.SelectOptionDict(
                        value=OFF_ACTION_TURN_OFF, label="Turn all entities off"
                    ),
                ],
            )
        ),
        # Only meaningful when Off action above is "Activate another
        # scene" - always shown (a form can't conditionally hide one
        # of its own fields) but only read/required in that case. Any
        # scene, not just ones tracked by this integration. Unlike the
        # text fields above, EntitySelector validates its value as an
        # actual entity id - an empty-string default fails that check
        # outright rather than meaning "unset", so the key is only
        # included at all when there's a real value.
        vol.Optional(
            CONF_OFF_SCENE_ENTITY,
            **(
                {"default": defaults[CONF_OFF_SCENE_ENTITY]}
                if defaults.get(CONF_OFF_SCENE_ENTITY)
                else {}
            ),
        ): selector.EntitySelector(selector.EntitySelectorConfig(domain="scene")),
        # Slack for numeric attributes (brightness, current_position,
        # temperature, etc.) only - the on/off state itself is always
        # compared exactly regardless. Exists for KNX<->HA rounding
        # drift (e.g. brightness 50% can convert back as 127 or 126)
        # - see comparator.py. Default 1 rather than 0 (exact match)
        # since that drift is common enough to be the sensible baseline.
        vol.Required(
            CONF_NUMERIC_TOLERANCE, default=defaults.get(CONF_NUMERIC_TOLERANCE, 1)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=20, mode="slider")
        ),
        # How long to wait after a tracked entity's state changes
        # before recomputing whether the scene is active - see
        # switch.py's module docstring for why this matters (coalesces
        # a burst of near-simultaneous changes into one recompute).
        # Different entity types settle at different speeds (a plain
        # switch is near-instant; a slow cover keeps reporting
        # position updates throughout its travel) so this is
        # per-tracker rather than a fixed global value.
        vol.Required(
            CONF_DEBOUNCE_SECONDS, default=defaults.get(CONF_DEBOUNCE_SECONDS, 1.5)
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.5, max=10, step=0.5, mode="slider", unit_of_measurement="s"
            )
        ),
    }
    if include_snapshot:
        # Lives here (state/snapshot page) rather than the tracker-basics
        # page, since it's about what gets captured into the snapshot the
        # state switch compares against - not about the tracker's KNX
        # identity (name/GA/scene number/entities).
        fields[
            vol.Required(CONF_SNAPSHOT_NOW, default=defaults.get(CONF_SNAPSHOT_NOW, True))
        ] = selector.BooleanSelector()
    return vol.Schema(fields)


# ---------------------------------------------------------------------------
# Validation / conflict checks
# ---------------------------------------------------------------------------


def _validate_tracker(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not GA_RE.match(user_input[CONF_GROUP_ADDRESS]):
        errors[CONF_GROUP_ADDRESS] = "invalid_ga_format"
    elif not user_input[CONF_ENTITIES]:
        errors[CONF_ENTITIES] = "no_entities"
    return errors


def _validate_state(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    state_ga = user_input.get(CONF_STATE_GROUP_ADDRESS)
    if state_ga and not GA_RE.match(state_ga):
        errors[CONF_STATE_GROUP_ADDRESS] = "invalid_ga_format"
    elif user_input[CONF_OFF_ACTION] == OFF_ACTION_ACTIVATE_SCENE and not user_input.get(
        CONF_OFF_SCENE_ENTITY
    ):
        errors[CONF_OFF_SCENE_ENTITY] = "off_scene_required"
    return errors


def _scene_id_conflict(hass, scene_id: str, exclude_entry_id: str | None = None) -> bool:
    """True if another tracker already computes to this scene id."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        existing_id = compute_scene_id(
            entry.data[CONF_GROUP_ADDRESS], int(entry.data[CONF_SCENE_NUMBER])
        )
        if existing_id == scene_id:
            return True
    return False


def _state_ga_conflict(hass, state_ga: str, exclude_entry_id: str | None = None) -> bool:
    """True if another tracker already uses this state group address.
    knx.exposure_register only supports one exposure per address."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        if entry.data.get(CONF_STATE_GROUP_ADDRESS) == state_ga:
            return True
    return False


def _tracker_conflicts(
    hass, user_input: dict[str, Any], exclude_entry_id: str | None = None
) -> dict[str, str]:
    scene_id = compute_scene_id(user_input[CONF_GROUP_ADDRESS], user_input[CONF_SCENE_NUMBER])
    if _scene_id_conflict(hass, scene_id, exclude_entry_id):
        return {CONF_SCENE_NUMBER: "already_configured"}
    return {}


def _state_conflicts(
    hass, user_input: dict[str, Any], exclude_entry_id: str | None = None
) -> dict[str, str]:
    state_ga = user_input.get(CONF_STATE_GROUP_ADDRESS)
    if state_ga and _state_ga_conflict(hass, state_ga, exclude_entry_id):
        return {CONF_STATE_GROUP_ADDRESS: "state_ga_already_configured"}
    return {}


def _next_available_scene_number(
    hass, group_address: str, exclude_entry_id: str | None = None
) -> int:
    """Lowest scene number 1-64 on `group_address` not already used by
    another tracker. Falls back to 1 if every number is somehow taken
    (the person will just hit the conflict error and need to free one up
    manually - extremely unlikely with 64 slots)."""
    used = set()
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.entry_id == exclude_entry_id:
            continue
        if entry.data.get(CONF_GROUP_ADDRESS) == group_address:
            used.add(int(entry.data[CONF_SCENE_NUMBER]))

    for candidate in range(1, 65):
        if candidate not in used:
            return candidate
    return 1


# ---------------------------------------------------------------------------
# Config flow (Add)
# ---------------------------------------------------------------------------


class KnxSceneSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle creation of a new KNX scene tracker."""

    VERSION = 1

    def __init__(self) -> None:
        self._tracker_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_tracker(user_input)
            if not errors:
                errors = _tracker_conflicts(self.hass, user_input)
            if not errors:
                self._tracker_data = user_input
                return await self.async_step_state_entity()

        return self.async_show_form(
            step_id="user",
            data_schema=_tracker_schema(user_input),
            errors=errors,
        )

    async def async_step_state_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_state(user_input)
            if not errors:
                errors = _state_conflicts(self.hass, user_input)
            if not errors:
                full_data = {**self._tracker_data, **user_input}
                scene_id = compute_scene_id(
                    full_data[CONF_GROUP_ADDRESS], full_data[CONF_SCENE_NUMBER]
                )
                await self.async_set_unique_id(scene_id)
                return self.async_create_entry(title=full_data[CONF_SCENE_NAME], data=full_data)

        return self.async_show_form(
            step_id="state_entity",
            data_schema=_state_schema(user_input, include_snapshot=True),
            errors=errors,
        )

    async def async_step_duplicate_import(
        self, import_data: dict[str, Any]
    ) -> config_entries.FlowResult:
        """Used internally by the options flow's Duplicate steps, which
        already validated the fields themselves - this just creates the
        entry directly, with no form of its own, so nothing needs to pop
        up as a separate dialog the person might not notice."""
        scene_id = compute_scene_id(
            import_data[CONF_GROUP_ADDRESS], import_data[CONF_SCENE_NUMBER]
        )
        await self.async_set_unique_id(scene_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=import_data[CONF_SCENE_NAME], data=import_data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> KnxSceneSyncOptionsFlow:
        # No arguments - self.config_entry is a property the flow
        # manager populates automatically after construction.
        return KnxSceneSyncOptionsFlow()


# ---------------------------------------------------------------------------
# Options flow (Edit / Duplicate)
# ---------------------------------------------------------------------------


class KnxSceneSyncOptionsFlow(config_entries.OptionsFlow):
    """Edit an existing tracker, or duplicate it as a new one - each as
    its own two-step wizard (tracker basics, then state switch settings).

    __init__ is safe to define here (unlike setting self.config_entry
    directly, which crashes on recent Home Assistant versions) since it
    only sets up unrelated instance state.
    """

    def __init__(self) -> None:
        self._tracker_data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["edit", "duplicate"])

    # -- Edit -----------------------------------------------------------

    async def async_step_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_tracker(user_input)
            if not errors:
                errors = _tracker_conflicts(self.hass, user_input, exclude_entry_id=entry.entry_id)
            if not errors:
                self._tracker_data = user_input
                return await self.async_step_edit_state()

        return self.async_show_form(
            step_id="edit",
            data_schema=_tracker_schema(user_input or entry.data),
            errors=errors,
        )

    async def async_step_edit_state(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_state(user_input)
            if not errors:
                errors = _state_conflicts(self.hass, user_input, exclude_entry_id=entry.entry_id)
            if not errors:
                full_data = {**entry.data, **self._tracker_data, **user_input}
                self.hass.config_entries.async_update_entry(
                    entry, title=full_data[CONF_SCENE_NAME], data=full_data
                )
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="edit_state",
            data_schema=_state_schema(user_input or entry.data),
            errors=errors,
        )

    # -- Duplicate --------------------------------------------------------

    async def async_step_duplicate(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Tracker-basics page for the duplicate, pre-filled from this
        entry with a fresh (non-colliding) scene number suggested."""
        source_entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_tracker(user_input)
            if not errors:
                errors = _tracker_conflicts(self.hass, user_input)
            if not errors:
                self._tracker_data = user_input
                return await self.async_step_duplicate_state()
            defaults = user_input
        else:
            defaults = dict(source_entry.data)
            defaults[CONF_SCENE_NUMBER] = _next_available_scene_number(
                self.hass, source_entry.data[CONF_GROUP_ADDRESS]
            )

        return self.async_show_form(
            step_id="duplicate",
            data_schema=_tracker_schema(defaults),
            errors=errors,
        )

    async def async_step_duplicate_state(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """State-switch page for the duplicate, then creates the new
        entry directly - all within this same open dialog."""
        source_entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_state(user_input)
            if not errors:
                errors = _state_conflicts(self.hass, user_input)
            if not errors:
                full_data = {**self._tracker_data, **user_input}
                result = await self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "duplicate_import"},
                    data=full_data,
                )
                if result.get("type") == FlowResultType.CREATE_ENTRY:
                    return self.async_create_entry(title="", data={})
                # Something unexpected stopped the new entry from being
                # created (e.g. a race against another tracker created in
                # the meantime) - surface it instead of silently doing
                # nothing.
                errors[CONF_STATE_GROUP_ADDRESS] = "duplicate_failed"
            defaults = user_input
        else:
            defaults = dict(source_entry.data)
            # A duplicated tracker needs its own status GA too - can't
            # share knx.exposure_register registration with the source.
            defaults.pop(CONF_STATE_GROUP_ADDRESS, None)

        return self.async_show_form(
            step_id="duplicate_state",
            data_schema=_state_schema(defaults, include_snapshot=True),
            errors=errors,
        )
