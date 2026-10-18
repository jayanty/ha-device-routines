# Device Routines

[![CI](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml)
[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)](https://hacs.xyz/docs/faq/custom_repositories/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/jayanty/ha-device-routines?include_prereleases)](https://github.com/jayanty/ha-device-routines/releases)

Device Routines adds start and stop times, run timers and a plain language schedule
summary to every Home Assistant device page, backed by real, clearly marked automations
that keep running even if the integration is removed.

> Status: pre-release. Phase 1, the read only Schedule summary, is being built: every device
> an automation acts on gets a Schedule sensor. Routines (the controls below) arrive in
> Phase 2. The roadmap is in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## What it does

- **Configure on the device page.** A device opted in to routines gets a small set of
  native controls in its Configuration card: Turn on at, Turn off at, Days, Turn off
  after, Turn back on after. They are Home Assistant's own time pickers, number fields
  and toggles, so there is nothing to learn.
- **See everything on the device page.** Every device that any automation acts on gets a
  Schedule sensor whose state reads like a sentence ("Off at 9:00 AM") and whose
  attributes list each routine and automation that controls the device, with its next run.
- **Home Assistant runs it.** Each routine is a normal automation built from a blueprint
  the integration ships. Traces, the automation list, the device page Automations card
  and git tracking of `automations.yaml` all work unchanged, and the routine keeps working
  if the integration is disabled.
- **Safe by refusal.** Nothing here will ever unlock a lock, open a garage door, gate or
  door, open a gas valve or disarm an alarm on a schedule. Those actions are refused in
  code, not merely hidden.
- **Local and private.** No cloud, no telemetry, no outbound calls. The optional AI
  summary goes only to an AI Task entity you select yourself.

## Install

Device Routines is distributed through [HACS](https://hacs.xyz/) as a custom repository
until it reaches the HACS default list.

1. In Home Assistant open HACS, then the three dot menu, then **Custom repositories**.
2. Add `https://github.com/jayanty/ha-device-routines` with the category **Integration**.
3. Find **Device Routines** in HACS and download it.
4. Restart Home Assistant.
5. Open **Settings**, **Devices & services**, **Add integration** and choose
   **Device Routines**. Setup has no fields.

Requires Home Assistant 2026.10 or newer.

## Documentation

- [User guide](docs/user-guide.md): reading the Schedule sensor.
- [Product requirements](docs/PRD.md): what the integration does and why.
- [Technical specification](docs/TECH_SPEC.md): how it is built.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md): the build order and validation.
- [Decisions log](docs/decisions-log.md): choices made during implementation.

## Development

The repository is public and generic: it never contains data from a real home. See
`CLAUDE.md` for the engineering rules.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest -m "not live" --cov
```

## License

[MIT](LICENSE).
