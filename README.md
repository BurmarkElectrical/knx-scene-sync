# KNX Scene Sync

KNX scenes as native Home Assistant entities, built around two ideas:

- **State** - every tracked scene has a switch that tells you whether it's
  *actually active right now*, by comparing your entities' live state
  against what the scene expects - not just whether it was the last thing
  triggered.
- **Sync** - activation, learning, and status all talk to the KNX bus
  directly (real DPT 18.001 telegrams), so Home Assistant and KNX never
  drift out of agreement with each other, in either direction.

> **Status:** early / actively developed. See `CHANGELOG.md` before
> upgrading - don't assume compatibility across versions until `1.0.0`.

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

## Quick start

Settings -> Devices & services -> Add integration -> "KNX Scene Sync".
It's a two-page form:

1. **Tracker basics** - display name, the KNX scene control group address
   (DPT 18.001), the KNX scene number (1-64), which entities belong to
   the scene, and whether to snapshot their current state immediately.
2. **State switch settings** - an optional KNX status group address, what
   happens when the switch is turned off, and tuning for the comparator
   (tolerance, debounce - see below).

Every field has an in-app description, so this README won't repeat them.
Use **Duplicate** (via the tracker's Configure menu) once you have one
set up - the common case is several scenes on the same lights/GA with
different scene numbers (bright/dim/off).

## What each tracker gives you

One device, with:

- **Scene** entity - activating it (its own Activate action, a
  dashboard, `scene.turn_on`) sends the KNX recall telegram directly,
  rather than calling a service on every member entity like a plain HA
  scene would. A real KNX-side learn telegram, or the Learn button here,
  snapshots current entity state into it.
- **State switch** - reflects whether the scene is currently active
  (see "Staying in sync" below). It's controllable, not just a sensor:
  on activates the scene, off runs a configurable action (do nothing,
  activate another scene, or turn everything off). Being a switch is
  what makes it usable as a HomeKit accessory via HA's HomeKit Bridge.
- **Snapshot Entities** / **KNX Learn Scene** buttons - under
  Diagnostic (not something you'd use day to day). Both require two
  presses to confirm, since both overwrite scene data - Learn a step
  further, bus-wide to every KNX device listening, not just this tracker.

Every snapshot or activation logs to the Home Assistant **Logbook**,
whether it came from KNX or a manual button press.

## Staying in sync

The state switch compares your entities' live state against the scene's
last snapshot on every relevant change:

- Entities with no snapshot value, or currently `unknown`/`unavailable`,
  are ignored.
- If everything ends up ignored, the switch reports **off**, not unknown.
- The on/off state itself is always compared exactly. Numeric attributes
  (brightness, cover position, temperature, etc.) can have a small
  **tolerance** (slider, default `1`) - KNX's percentage byte and HA's
  0-255 brightness scale don't convert losslessly, so an exact-match
  comparator can flicker "inactive" on scenes that are, for all practical
  purposes, correct.
- Changes are **debounced** (slider, default `1.5s`) so a burst of
  entities settling after a scene recall triggers one recompute, not
  several. This reduces noise during a transition - it doesn't make the
  switch wait for a slow entity (a travelling cover, say) to finish;
  that already happens naturally since it just won't match until it's
  actually done.
- A fresh snapshot (learn or Snapshot button) is evaluated immediately,
  since the comparison target itself just changed.

**KNX status feedback**: set a status group address on page 2 and the
switch's value is pushed to the bus and answers `GroupValueRead`
automatically, via `knx.exposure_register` - not a hand-rolled listener.
Optional; leaving it blank only affects bus visibility, not HA/HomeKit.

## Supported entities

Any KNX-provided entity can be added - the picker isn't domain-limited.
Snapshot/comparison captures `state` plus, per domain:

| Domain | Attributes |
|---|---|
| Light | `brightness`, `rgb_color`, `rgbw_color`, `color_temp_kelvin`, `xy_color`, `hs_color`, `effect` |
| Cover | `current_position`, `current_tilt_position` |
| Climate | `temperature`, `fan_mode`, `preset_mode` |
| Fan | `percentage`, `preset_mode`, `oscillating`, `direction` |

Locks and media players aren't specifically supported - only bare
`state` would be captured, and "snapshot and compare" isn't a natural
fit for either. Raise an issue if you have a concrete use case.

## Notes / limitations

- Entity ids are derived from group address + scene number
  (`scene.knxsync_...`, `switch.knxsync_..._state`), not display name -
  renaming a tracker never changes them; editing the GA/scene number does.
- The scene's `last_snapshot` attribute is for visibility/history only -
  activation always sends the KNX telegram and relies on the actuators'
  own stored values, never replays the snapshot itself.
- The Scene and state switch entities load concurrently, so there's a
  brief window on startup where the switch may show "off" before the
  scene has finished loading its snapshot - self-corrects within the
  same startup pass.
- No "Back" button in the two-page wizard - a Home Assistant flow
  limitation. Cancel and restart if you need to change page 1.
- Home Assistant has no way to customize a config flow's "Submit" button
  text (a still-open upstream feature request), which is why step titles
  are numbered `(1/2)`/`(2/2)` instead.

## Debug logging

```yaml
logger:
  logs:
    custom_components.knx_scene_sync: debug
```

Logs per-entity comparison detail (compared/ignored/matched/mismatched),
the final active/inactive verdict, and debounce timer activity.

## Brand images

`custom_components/knx_scene_sync/brand/` ships a placeholder icon and
logo (an original abstract sync-arrows + spark design, not KNX's actual
trademarked mark) - HA 2026.3+ reads these directly from the integration
folder, no submission to the separate `home-assistant/brands` repo
needed. Replace `icon.png` / `logo.png` (and their `@2x` variants) with
real artwork whenever you have some; same filenames, same folder.

## Contributing

Bug reports, feature requests, and PRs welcome - see `CONTRIBUTING.md`.

## License

[MIT](LICENSE)
