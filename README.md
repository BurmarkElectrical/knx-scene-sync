# KNX Scene Sync

KNX scene control (DPT 17.001 and DPT 18.001) for Home Assistant - set
and learn KNX scenes directly on the bus, while tracking entity state for
live scene feedback.

## Requirements

- Home Assistant's core **KNX integration** already set up and connected
  to your bus.

- The scenes themselves already **configured on your KNX devices in
  ETS** - a scene control object (DPT 17.001 or DPT 18.001) assigned to
  a group address, with each relevant actuator set to recall (and, for
  DPT 18.001, learn) on the scene number(s) you want. This integration
  doesn't create scene behavior on the KNX side - it activates, learns,
  and tracks scenes that already exist on the bus.
  
- The entities you want to track already set up in Home Assistant via
  the KNX integration (lights, covers, climate, fans - see "Supported
  entities" below), since they need to be selectable when adding a
  tracker.

## Install

### Home Assistant Community Store (HACS)

If you don't have HACS installed, follow the
[documentation here](https://hacs.xyz/docs/setup/prerequisites).

1. Open HACS in Home Assistant.
2. Select `Custom repositories` using the three dots in the top right.
3. Add `https://github.com/BurmarkElectrical/knx-scene-sync`.
4. Select `Integration` as the category.
5. Find `KNX Scene Sync` in HACS, select Download, then restart Home
   Assistant.
6. Go to `Settings` -> `Devices & services` -> `Add integration` and
   search for `KNX Scene Sync`.
7. Follow the prompts to add your first tracker.

### Manual installation

Copy `custom_components/knx_scene_sync/` into
`config/custom_components/`, then restart Home Assistant.

## Scene tracker

#### `Scene`

The `scene` represents the KNX scene in HA. Activating it sends the KNX
recall telegram directly to the bus, instead of controlling every member
entity like a plain HA scene would. It stores a snapshot of its
entities, which the state switch below uses for feedback.

#### `State switch`

State switch tracks whether the scene is currently active by comparing
live entity state against that snapshot.
The scene state will be sent onto the bus when you configure the group
address, it will also respond to `GroupValueRead`.
Turning the state switch `on` activates the scene, `off` runs a
configurable action.

#### `KNX Learn Scene`

KNX Learn Scene button sends a KNX learn telegram to the bus. Devices
configured to learn on that scene number will store their current
output as the scene. The integration also captures a matching entity
snapshot at the same time. Only available for DPT 18.001 trackers - see
"Group address type" below.

#### `Snapshot Entities`

Snapshot Entities button overwrites the stored scene snapshot on the HA
side only, with no KNX traffic. General practice is to set the entities
to the desired state first, then use **KNX Learn Scene** instead - that
keeps both the KNX devices and HA entities in sync.

## Group address type

Each tracker's control group address can be either:

- **DPT 18.001 (recall + learn)** - the default. Supports everything
  above, including the KNX Learn Scene button and KNX-side learning.
- **DPT 17.001 (recall only)** - a plain 1-byte scene number with no
  control bit, so there's no way to signal "store" on the wire. The
  KNX Learn Scene button isn't shown for these trackers, since there's
  no valid telegram it could send. Recall (from HA or from KNX), the
  state switch's live feedback, and the Snapshot Entities button all
  work exactly the same either way - only KNX-triggered learning is
  unavailable. A recall seen on the bus for a DPT 17.001 tracker is
  still logged to the Logbook, without triggering a snapshot.

## Comparison behavior

- Entities with no snapshot value, or `unknown`/`unavailable`, are ignored. All-ignored means **`off`**, not unknown.
- State is always compared exactly. Numeric attributes (brightness, position, temperature) allow a small **tolerance** (default `1`) to absorb KNX<->HA rounding drift.
- Changes are **debounced** (default `1.5s`) so a burst of entities settling after a recall triggers one recompute, not several.
- **Status group address** (optional) exposes the switch's value to KNX and answers `GroupValueRead`, via `knx.exposure_register`.

## Supported entities

Any KNX-provided entity can be tracked. Captures `state` plus, per
domain:

| Domain | Attributes |
|---|---|
| Light | `brightness`, `rgb_color`, `rgbw_color`, `color_temp_kelvin`, `xy_color`, `hs_color`, `effect` |
| Cover | `current_position`, `current_tilt_position` |
| Climate | `temperature`, `fan_mode`, `preset_mode` |
| Fan | `percentage`, `preset_mode`, `oscillating`, `direction` |

Locks and media players aren't specifically supported - open an issue if
you have a concrete use case.

## Debug logging

```yaml
logger:
  logs:
    custom_components.knx_scene_sync: debug
```

## Contributing / License

PRs and issues welcome - see `CONTRIBUTING.md`. [MIT](LICENSE).
