# Contributing

This is a young, actively-developed project - contributions, bug reports,
and design feedback are all welcome.

## Development setup

This is a standard Home Assistant custom integration - there's no separate
build step. To test changes:

1. Copy `custom_components/knx_scene_sync/` into a Home Assistant
   instance's `config/custom_components/` directory (a dev container or
   VM running Home Assistant Core is easiest for iterating).
2. Restart Home Assistant after any code change - Python modules are only
   imported once per process, so edits aren't picked up by a simple
   integration reload.
3. Enable debug logging while testing:

   ```yaml
   logger:
     logs:
       custom_components.knx_scene_sync: debug
   ```

## Before submitting a PR

- Run `python -m py_compile custom_components/knx_scene_sync/*.py` and
  make sure `strings.json` / `translations/en.json` stay in sync (they
  should always be identical copies).
- If you add or rename a config flow field, update `strings.json` for
  every affected step (`config.step.*` and `options.step.*`) - a missing
  translation falls back to showing the raw field key, which is the
  fastest way to notice a gap.
- Update `README.md` if the change affects user-facing behavior.
- Bump the `version` in `manifest.json` following semver.

## Reporting bugs

Please include a debug log snippet (see the bug report template) -
`comparator.py` and `switch.py` log per-entity comparison detail at debug
level, which is usually enough to diagnose a scene-state issue without
back-and-forth.
