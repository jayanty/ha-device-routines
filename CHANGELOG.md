# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Build A (Phases 2 and 3) is in progress; the entries below grow with it.

### Added

- Routine controls on every opted in device page: Routine, Turn on at and Turn off at
  (worded for the device: Start at, Open at, Lock at), Days, Turn off after, Turn back on
  after, Catch up after restart, Respect manual changes, Skip next, Paused until, Resume,
  Manual override, and Routine controls when a device has several entities; a Clean up now
  button on the hub.
- Every Schedule sensor carries two more attributes, `paused_until` and `skipped_action`
  (empty until a device has a routine), and a device's routine line sorts first.
- The integration installs its routine blueprint
  (`blueprints/automation/device_routines/device_routine.yaml`) and creates the `Routines`
  label and the `Device Routines` automation category at setup, and keeps them in place:
  a missing blueprint is reinstalled, a hand edited one is left alone and reported in
  Repairs.
- Actions `device_routines.skip_next`, `pause` (until a time or for a duration), `resume`,
  `enable`, `disable` and `maintenance`, with device, area, floor, label and entity
  targets and an optional response listing what each target did and which targets have
  no routine.
- Automation triggers "Routine action skipped", "Routine paused" and "Routine resumed" and
  conditions "Routine is paused" and "Routine is active", with device, area, floor, label
  and entity targets.
- Repairs for routines: a changed blueprint, settings edited into an invalid state, a
  routine taken over in the editor, an empty weekly schedule, a lost save race, a routine
  that does not load and (with Raise conflict repairs on) a routine colliding with another
  automation; every fixable one has a one step fix.
- A WebSocket API for the coming console (routines, actions, opting devices in, the day's
  schedule, settings, maintenance and a subscription), documented in `docs/api.md`.
- Health now reports the blueprint's status and schema, how many routines exist and load,
  the open Repairs issues and the last reconcile, and reads `degraded` or `error` when
  something needs attention; diagnostics cover routines with every id and name redacted.
- The user guide covers giving a device a routine, skip, pause and resume, weekly
  schedules, Turn back on after, pulse, the managed automation, editing it yourself,
  removal, dashboards and scripts, supported devices, settings, troubleshooting and the
  limitations.
- Setup offers the devices that already have time based automations (optional); the
  options are a menu of Settings (every global setting), Devices with routines and
  Suggested devices; removing the integration keeps every routine running as a normal
  automation (On removal: keep) or deletes them with their helpers (delete).

## [0.1.0] - 2026-10-18

The read only Schedule summary (Phase 1).

### Changed

- The test harness is pinned to core 2026.10.2 (harness 0.13.373), the version the
  development instance runs, and HACS requires at least that version: Stage 0 validated
  the integration's assumptions on it.

### Added

- A read only live suite in `tests/live/` for the development instance (skipped without
  `local/live.env`).

- `docs/user-guide.md` with the section Reading the Schedule sensor.
- The golden corpus now pins the exact summary lines for the 39 captured automations and 12
  synthetic ones covering the grammar.
- Hub entities Routines (count of active routines, 0 until routines ship) and Problem
  (on while a Device Routines Repairs issue is open), a settings page in the options
  (Schedule sensor scope, time format), the Repairs issue raised when the running Home
  Assistant lacks what the summary needs, and diagnostics that report the summary as
  shapes and counts only.
- A Schedule sensor on every device an automation acts on, directly or through its area,
  floor or a label: the next action as a sentence ("Off at 9:00 AM") and one line per
  automation action in its attributes, recomputed on every change without polling. The
  Schedule sensor scope option (all, routines, none) decides where it appears.
- The schedule summary's pure core (Phase 1 task 1.1): domain profiles with the refused
  actions, a deterministic automation parser whose grammar is data, next runs that follow
  the core time trigger on daylight saving nights, the sentence writer with its English
  phrase table and the 40 character state cap, conflict detection and the global settings
  catalog with defaults and validation.
- Stage 0 harness probes in `tests/stage0/`: restored timers, schedule blocks at midnight,
  daylight saving nights, `datetime` entities in time triggers and conditions, the area,
  floor and label reference helpers, blueprint install and features, the automation write
  path, helper creation, attaching entities to devices and custom purpose specific
  triggers and conditions. Each records what the pinned core does, so a core upgrade that
  changes an answer fails CI.

- Golden corpus seed: 39 anonymized automations captured read only from a real instance
  in Stage 0, each validated against the pinned core, and `tools/scrub_automations.py`,
  which strips free text and opaque ids from captures before they are anonymized.
- CI on every push and pull request: lint, strict typing, tests on the pinned and the
  latest core, hassfest, HACS validation, the privacy and style checks and the deploy tool
  parity check; a green push to `dev` moves the `dev-stable` tag. A `v*` tag builds the
  HACS zip and publishes a release with notes from this file.
- Home Assistant package `tools/ha_package/device_routines_dev.yaml` for the development
  channel: the shell commands, the REST sensor watching `dev-stable`, the helpers and the
  three automations that deploy, restart inside an opt in window, roll back after a
  failed start and remember the last commit that loaded (also when it loaded during
  startup), with a README covering the bootstrap and the restart policy.
- Deploy tool `tools/ha_deploy.py` v1.1, shared with the sibling repository: deploys a
  tag, branch or commit (default the `dev-stable` tag CI promotes) into the running
  instance without ever restarting it, is idempotent, says whether a restart, an
  automation reload or a browser reload is needed, keeps five backups, refuses a second
  rollback in a row and reports the deployed commit, the HACS channel and whether the
  deployed code parses.
- Integration skeleton: a zero field config flow creating the single entry, the hub
  service device with its Health sensor (version, running commit, channel, Home
  Assistant version and the self check fields), config entry diagnostics with secret
  shaped options redacted, translations, icons and the quality scale checklist with every
  official rule accounted for.
- Privacy tooling: `tools/privacy_check.py` (pre commit hook on staged content and the
  commit message, generic patterns in CI), `tools/make_denylist.py` (builds the private
  denylist from a registries capture), `tools/anonymize.py` (turns raw captures into
  fixtures with stable generic stand ins) and `tools/style_check.py` (refuses the em dash
  character), each with unit tests.
- Repository skeleton: tooling configuration (ruff with every rule on, mypy strict,
  pytest with the Home Assistant test harness pinned to the validated core, coverage gate at
  95 percent), the MIT license, HACS metadata, issue and pull request templates,
  Dependabot, placeholder brand images and the decisions log.

### Fixed

- Several state triggers that wait for the same change now read as one clause ("When A, B
  or C changes") instead of a chain of "or when" clauses.
- An automation acting on a device several times the same way no longer repeats the same
  Schedule line.

