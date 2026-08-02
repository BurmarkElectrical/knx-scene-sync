# KNX Scene Sync

DPT 18.001 (scene control) for Home Assistant, built for scene setting
native KNX scenes while tracking entity state for scene feedback.

## Install

### Home Assistant Community Store (HACS)

If you dont have HACS installed, follow [documentation here](https://hacs.xyz/docs/setup/prerequisites)

1. Open HACS in Home Assistant
2. Select `Custom Repositories` using the 3 dots in top right
3. Add `https://github.com/BurmarkElectrical/knx-scene-sync`
4. Select `Integration` as category
4. Search `KNX Scene Sync` in `Repository Name`, download it and restart HA
5. Go to `settings` -> `Devices & Service` -> `Add Integration` and search for `KNX Scene Sync`
6. Follow prompts to add tracked scenes

**Manual**: copy `custom_components/knx_scene_sync/` into
`config/custom_components/`, then restart Home Assistant.

## Scene Tracker

- **Scene** entity - Like a KNX scene in HA, activating it sends the KNX recall telegram
  directly to the bus, instead of controlling every member entity like a plain HA
  scene would. 

  The scene stores its entities snapshot for status feedback.

- **State switch** - tracks whether the scene is currently active by
  comparing live entity state against a snapshot. 

  When a DPT 18.001 learn telegram is received from the bus, the trackers automatically update their snaphots.

  Controllable switch (needed for HomeKit): `on` activates the scene, `off` runs a configurable action.

- **KNX Learn Scene** button - sends a KNX learn telegram to the bus. Devices configured to learn the KNX scene number will store its current state. The integration will also take an entitiy snaphot at this time.

- **Snapshot Entities** button - Overwrite stored scene snaphot. Its general practice to change the entities to the desired state, then use the **KNX Learn Scene** button - that way KNX devices and HA entities are in sync.

## Comparison behavior

- Entities with no snapshot value, or `unknown`/`unavailable`, are
  ignored. All-ignored means **off**, not unknown.
- State is always compared exactly. Numeric attributes (brightness,
  position, temperature) allow a small **tolerance** (default `1`) to
  absorb KNX<->HA rounding drift.
- Changes are **debounced** (default `1.5s`) so a burst of entities
  settling after a recall triggers one recompute, not several.
- **Status group address** (optional) exposes the switch's value to KNX
  and answers `GroupValueRead`, via `knx.exposure_register`.

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