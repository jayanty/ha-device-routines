# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The test harness is pinned to core 2026.10.2 (harness 0.13.373), the version the
  development instance runs, and HACS requires at least that version: Stage 0 validated
  the integration's assumptions on it.

### Added

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
