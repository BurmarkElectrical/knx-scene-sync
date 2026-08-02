"""Constants for the KNX Scene Sync integration."""
import re

DOMAIN = "knx_scene_sync"

CONF_GROUP_ADDRESS = "group_address"
CONF_GA_TYPE = "ga_type"
CONF_SCENE_NUMBER = "scene_number"
CONF_SCENE_NAME = "scene_name"
CONF_ENTITIES = "entities"
CONF_SNAPSHOT_NOW = "snapshot_now"
CONF_STATE_GROUP_ADDRESS = "state_group_address"
CONF_OFF_ACTION = "off_action"
CONF_OFF_SCENE_ENTITY = "off_scene_entity"
CONF_NUMERIC_TOLERANCE = "numeric_tolerance"
CONF_DEBOUNCE_SECONDS = "debounce_seconds"

# DPT 18.001: recall + learn (control bit distinguishes them).
# DPT 17.001: recall only, plain 1-byte scene number, no control bit at
# all - there is no valid telegram that could mean "store" on the wire.
GA_TYPE_DPT18 = "dpt18"
GA_TYPE_DPT17 = "dpt17"

OFF_ACTION_NONE = "none"
OFF_ACTION_ACTIVATE_SCENE = "activate_scene"
OFF_ACTION_TURN_OFF = "turn_off_entities"

GA_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{1,3}$")

# Attributes captured on top of state when snapshotting an entity. This is
# checked per-entity via `if attr in state.attributes`, so adding more
# names here is purely additive - a light simply won't have
# "current_position" in its attributes, so it's silently skipped. Grouped
# by the domain each is relevant to; light entities were the original
# (and still primary) case.
SNAPSHOT_ATTRIBUTES = (
    # light
    "brightness",
    "rgb_color",
    "rgbw_color",
    "color_temp_kelvin",
    "xy_color",
    "hs_color",
    "effect",
    # cover
    "current_position",
    "current_tilt_position",
    # climate (hvac_mode itself is climate's `state`, captured separately)
    "temperature",
    "fan_mode",
    "preset_mode",
    # fan
    "percentage",
    "oscillating",
    "direction",
)

# Prefix for every scene id this integration generates - kept as a single
# named constant so it's easy to change in one place if ever needed.
SCENE_ID_PREFIX = "knxsync_"


def compute_learn_payload(scene_number: int) -> int:
    """Encode a DPT 18.001 store (learn) telegram byte for `scene_number`.

    Bit 7 set = store/learn, low 6 bits = scene number - 1.
    e.g. scene_number=23 -> 0x80 | 22 = 150
    """
    return 0x80 | (int(scene_number) - 1)


def compute_recall_payload(scene_number: int) -> int:
    """Encode a recall (activate) telegram byte for `scene_number`.
    Shared by DPT 17.001 and DPT 18.001 - both encode scene number - 1 in
    the low 6 bits, DPT 18.001 with bit 7 clear (DPT 17.001 has no
    control bit at all). e.g. scene_number=23 -> 22
    """
    return int(scene_number) - 1


def compute_scene_id(group_address: str, scene_number: int) -> str:
    """Derive a stable, readable scene id from GA + KNX scene number.

    e.g. ("1/2/3", 23) -> "knxsync_1_2_3_23"
    This is independent of the user-editable display name, so renaming
    a tracker in the UI never changes its underlying scene.* entity_id.
    """
    ga_slug = re.sub(r"[^0-9a-z]+", "_", group_address.lower()).strip("_")
    return f"{SCENE_ID_PREFIX}{ga_slug}_{int(scene_number)}"


def device_info_for_entry(entry) -> dict:
    """Shared device grouping for every entity belonging to one tracker."""
    ga = entry.data[CONF_GROUP_ADDRESS]
    scene_number = int(entry.data[CONF_SCENE_NUMBER])
    return {
        "identifiers": {(DOMAIN, entry.entry_id)},
        "name": entry.data[CONF_SCENE_NAME],
        "manufacturer": "KNX Scene Sync",
        "model": f"GA {ga} · Scene {scene_number}",
    }
