# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/), versions follow
[Semantic Versioning](https://semver.org/).

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
