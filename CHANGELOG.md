# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/), versions follow
[Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-08-05

### Added
- Optional **Icon** field on page 1 of Add/Edit/Duplicate, using Home
  Assistant's native icon picker. Applied to both the Scene and State
  switch entities, so both match without setting each individually via
  entity settings. Leave blank for the normal default icon.

## [0.3.2] - 2026-08-05

### Fixed
- "Run an action on an entity" off action silently doing nothing when
  the target was a scene entity. Home Assistant's generic
  `homeassistant.turn_on`/`turn_off`/`toggle` services skip domains that
  don't support "turning on" in that generic sense, and scenes -
  stateless by design, no real on/off - are one of them; the call
  completed with no error while doing nothing at all. Scene targets now
  call `scene.turn_on` directly (the only thing a scene supports),
  regardless of which action is selected.

## [0.3.1] - 2026-08-05

### Fixed
- Editing a tracker still carrying a pre-0.3.0 Off action value (e.g.
  the old "Activate another scene") could silently resubmit that stale
  value unchanged - the Edit form's Off action dropdown was defaulting
  to a value that no longer exists as an option, which doesn't render
  as a real selection. The form now falls back to "No action" for any
  stored value it doesn't recognize, so it's always a real, visible
  selection you can consciously change.

## [0.3.0] - 2026-08-04

### Changed
- **Breaking:** the state switch's "Activate another scene" off action
  has been replaced with a more general **"Run an action on an entity"**
  - an entity picker (any entity, no domain restriction) plus a
  Turn on / Turn off / Toggle action, calling Home Assistant's generic
  `homeassistant.turn_on`/`turn_off`/`toggle` services. This covers
  activating another scene (pick the scene entity, Turn on - identical
  behavior to before) as well as new cases like an all-off group switch.
  Any tracker previously configured with "Activate another scene" needs
  reconfiguring on page 2 of its Edit dialog - the old option and its
  stored entity are no longer read.
- Trimmed the state switch config flow's field help text across all
  three steps (Add/Edit/Duplicate page 2) - same information, much
  shorter (e.g. the tolerance/debounce descriptions dropped from
  400+ characters to under 150).

### Fixed
- A tracker with a stale/unrecognized Off action value (e.g. the old
  "Activate another scene" from before this version) previously fell
  through silently to "Turn all entities off" instead of erroring or
  doing nothing - the final branch wasn't actually gated by a value
  check. Now explicitly checked, with an unrecognized value logging a
  warning and doing nothing instead of guessing.

## [0.2.1] - 2026-08-04

### Fixed
- Trackers failing to set up when the KNX interface was still offline or
  reconnecting at Home Assistant startup, requiring a manual reload of
  every tracker to recover. `dependencies: ["knx"]` in `manifest.json`
  only guarantees the KNX component's code loads first - it doesn't wait
  for KNX's own config entry to finish connecting, so the initial
  `knx.event_register` call could hit KNX's module data before it
  existed. Now caught and re-raised as `ConfigEntryNotReady`, so Home
  Assistant retries the tracker automatically with backoff instead of
  leaving it in a permanently failed state.

## [0.2.0] - 2026-08-02

### Added
- **DPT 17.001 support**: trackers can now use a plain recall-only scene
  control group address instead of DPT 18.001. New "Group address type"
  field on page 1 of the config flow. Since DPT 17.001 has no control bit
  at all, there's no valid telegram that could mean "store" - the
  **KNX Learn Scene** button is omitted entirely for these trackers
  (not shown disabled - genuinely not possible), and the bus listener
  treats every telegram as a recall, logging it to the Logbook without
  triggering a snapshot. Recall (from HA or KNX), the state switch's live
  feedback, and the **Snapshot Entities** button all work identically
  regardless of which DPT is chosen.

## [0.1.0] - 2026-08-02

Initial structured release under the name **KNX Scene Sync** (developed
and tested through several iterations previously as "KNX Scene
Tracker" - renamed before first public release, so there is no migration
path from that name).

### Added
- Per-tracker **Scene** entity. Activating it sends a DPT 18.001 recall
  telegram instead of individually controlling every tracked entity, so
  HA-triggered and KNX-triggered activation behave identically and bus
  traffic stays to one telegram.
- **Learn (store) telegram** support: a real KNX-side learn, or the
  **KNX Learn Scene** button looping its own telegram back through the
  same listener, both snapshot the tracked entities' current state into
  the scene.
- **Snapshot Entities** button for an HA-only snapshot, no KNX traffic.
  Both buttons are gated behind an arm-then-confirm double press, and
  categorized as Diagnostic rather than Controls.
- **State switch** per tracker: compares live entity state against the
  scene's snapshot to report whether the scene is currently active,
  independent of how that match came about. Controllable (needed for
  HomeKit exposure via Home Assistant's HomeKit Bridge) - turning it on
  activates the scene, turning it off runs a configurable **Off action**
  (no action / activate another scene / turn all entities off).
- Configurable **numeric attribute tolerance** (default 1) to absorb
  KNX<->HA rounding drift (e.g. brightness 50% converting to 127 or 126
  depending on rounding direction).
- Configurable **debounce time** (default 1.5s) to coalesce a burst of
  near-simultaneous entity updates into one recompute.
- Optional **KNX status group address** exposing the state switch's
  value to the bus and answering `GroupValueRead` requests, via Home
  Assistant's `knx.exposure_register` action.
- Snapshot/attribute support for **light, cover, climate, and fan**
  entities.
- Two-step configuration wizard (tracker basics, then state switch
  settings) for Add, Edit, and Duplicate.
- Activity logged to the Home Assistant **Logbook** for every snapshot
  and activation, distinguishing KNX-triggered from manual actions.

