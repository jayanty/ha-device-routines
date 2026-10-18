# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-18

Sun times, Only when, conversion offers and the console (Phase 4), first published as the
pre release `v1.0.0-beta.1`. The first start of this version moves every routine to
routine blueprint input schema 2 with the same behavior.

### Added

- Turn on at and Turn off at accept sunrise or sunset, up to three hours before or after
  (routine blueprint input schema 2). Each time has two advanced device page controls,
  disabled by default: a timing select (Time, Sunrise, Sunset, in the device's own words,
  such as Start timing or Lock timing) and a sun offset in minutes; the routine's
  automation form offers the same choice. A window from sunset to sunrise runs across
  midnight and belongs to the day it starts on, like any other window.
- Only when conditions show in the Schedule line of the actions they gate: "Weekdays
  9:45 AM: start (if 1 condition passes)".
- RoutineView carries `opted_in`, and the `ignored` targets of a routine action carry
  `placeholders` for their message.
- Conversion offers: a hand written automation that does exactly what a routine does (two
  times that turn one device on and off, or Turn off after) is offered in Repairs as "can
  become a routine", showing both sentences. Confirming creates the routine, turns the
  automation off and labels it `Replaced by routine`; turning it back on is the undo. The
  offers follow the Offer to convert matching automations setting, and the WebSocket API
  gains `conversions/list` and `conversions/convert`.
- The `schedule/today` WebSocket items carry the device name, the automation's alias and
  how many conditions gate each action.
- The Device Routines console: an admin only sidebar panel with three views. Routines lists
  every routine with its sentence, status, next action and pause, with Skip next, pause,
  resume, enable and disable per row or for a selection, opt in and out, inline settings
  and the conversion offers; Today shows the day's actions in the house by area and time
  with conflicts highlighted; Settings edits every global setting, runs the maintenance
  actions with a preview first and shows Health.

### Changed

- The routine's automation form shows only what a person chooses: the inputs Device
  Routines sets itself (the helpers it keeps and the values it derives) move into a last
  section, "Set by Device Routines (do not edit)", which starts collapsed; the four it sets
  that have no default stay under Target, marked "Set by Device Routines". The stored
  inputs and their meaning are unchanged.
- Final icon and logo, in light and dark, with the `home-assistant/brands` layout under
  `brand/brands/`.
- A routine change answers the conflicts of its new settings at once, and the Today view
  follows them, instead of after the routine is written.
- The Schedule state reads a sunrise or sunset to the whole minute ("On at 7:26 AM").
- The routine blueprint moves to input schema 2. At the first start of this version
  Device Routines installs it and rewrites every routine's automation to schema 2 with
  the same behavior, keeping the previous inputs in its store. A routine still on schema 1
  keeps running unchanged on the new blueprint until it is rewritten.

### Fixed

- A routine written at the same time as other routines no longer loses its Turn off after
  timer. Before, a sync of `automations.yaml` that read the file just before the routine's
  first write could treat the routine as deleted by hand and delete its timer, so Turn off
  after did nothing until the next start of Home Assistant (`v1.0.0-beta.1` and 0.3.0).
- A routine whose Turn off at is midnight (12:00 AM) no longer counts as on for the whole
  next day: a restart, a reconnect or a cleared manual override on that day turned the
  device on. Version 0.3.0 has this fault.
- An automation with a time condition holding only `before: 00:00:00` reads as the core
  runs it (always true) in the Schedule summary.
- Open conversion offers no longer count as problems: the hub Problem sensor stays off and
  Health does not list them.
- A routine bounded by sunrise or sunset gets its window conflicts (an automation turning the
  device on inside its off window, or off inside its on window).
- Deleting a routine's automation in the automation editor resets the routine (or clears
  a taken over routine's Repairs issue) at once; Home Assistant reloads nothing on a
  delete, so 0.3.0 waited for the next reload.
- A device whose automations are all turned off reads "Automation off" or "Automations
  off" instead of the first automation's next action.
- A hand written automation with a duration too large to represent no longer stops the
  Schedule summary from reading the other automations.

## [0.3.0] - 2026-10-18

Routines (Phases 2 and 3), first published as the pre release `v0.3.0-beta.1`. Version
0.2.0 is skipped: both phases ship together. Existing Phase 1 settings and stored data
migrate on the first start.

### Added

- Routine controls on every opted in device page: Routine, Turn on at and Turn off at
  (worded for the device: Start at, Open at, Lock at), Days, Turn off after (Close after on
  a blind or a valve, Lock after on a lock), Turn back on after, Catch up after restart,
  Respect manual changes, Skip next, Paused until, Resume, Manual override, and Routine
  controls when a device has several entities; a Clean up now button on the hub. Each
  routine is a normal automation built from the shipped blueprint, which Home Assistant
  runs with or without the integration.
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
- Weekly schedules: Days set to Weekly schedule creates a labeled schedule helper named
  after the device, whose blocks drive the routine; Skip next skips the next block.
- The hub Routines sensor counts the active routines and lists every routine with its
  device, area, summary, next action, status and automation.
- An optional AI summary for automation lines the parser cannot read, sent only to an AI
  Task entity you choose, as the automation's blocks with entity ids and no names; off by
  default.

### Changed

- The Schedule summary reads more automations without guessing: state triggers that list
  several states, `event.received` with its event types, and a timer's own started,
  finished and cancelled events; purpose specific triggers with options that change their
  meaning now read as custom logic instead of a plain line.

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

