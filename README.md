# Device Routines

[![CI](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml)
[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)](https://hacs.xyz/docs/faq/custom_repositories/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/jayanty/ha-device-routines?include_prereleases)](https://github.com/jayanty/ha-device-routines/releases)

Device Routines adds start and stop times, run timers and a plain language schedule
summary to every Home Assistant device page, backed by real, clearly marked automations
that keep running even if the integration is removed.

> **Status.** Version 0.1.0 is released: every device an automation acts on gets a
> Schedule sensor that says what will happen to it next. Routines (the device page
> controls, skip and pause, the actions, triggers and conditions) are being built and
> tested now and ship in version 0.3.0, first as a `v0.3.0-beta.1` pre release. The
> [user guide](docs/user-guide.md) already describes them; the roadmap is in
> [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## What it does

- **Configure on the device page.** A device opted in to routines gets a small set of
  native controls in its Configuration card: Turn on at, Turn off at, Days, Turn off
  after, Turn back on after. They are Home Assistant's own time pickers, number fields
  and toggles, so there is nothing to learn. A vacuum shows "Start at", a blind "Open at".
- **See everything on the device page.** Every device that any automation acts on gets a
  Schedule sensor whose state reads like a sentence ("Off at 9:00 AM") and whose
  attributes list each routine and automation that controls the device, with its next run.
- **Not now, in one tap.** Skip next, Paused until and Resume on the device page, and as
  actions for a whole room or label from a dashboard or script.
- **Survives restarts.** Run timers are timer helpers that keep their remaining time, and
  a missed start or stop is caught up when Home Assistant starts or the device comes back.
  A change made by hand is respected until the next scheduled time.
- **Home Assistant runs it.** Each routine is a normal automation built from a blueprint
  the integration ships. Traces, the automation list, the device page Automations card
  and git tracking of `automations.yaml` all work unchanged, and the routine keeps working
  if the integration is disabled or removed.
- **Unmistakable.** Every managed automation carries its own id prefix, blueprint, alias,
  category, label and icon. The integration only ever writes to automations it created;
  your own automations are read for the summary and never changed.
- **Safe by refusal.** Nothing here will ever unlock a lock, open a garage door, gate or
  door, open a gas valve or disarm an alarm on a schedule. Those actions are refused in
  code, not merely hidden.
- **Zero upkeep.** Setup has no fields. Renamed devices, a restored `automations.yaml`,
  missing helpers and removed devices heal on their own; Repairs asks only when a person
  has to decide, with a one click fix.

## Install

Device Routines is distributed through [HACS](https://hacs.xyz/) as a custom repository
until it reaches the HACS default list.

1. In Home Assistant open HACS, then the three dot menu, then **Custom repositories**.
2. Add `https://github.com/jayanty/ha-device-routines` with the category **Integration**.
3. Find **Device Routines** in HACS and download it. To try routines before 0.3.0 is
   final, let HACS show pre releases for this repository.
4. Restart Home Assistant.
5. Open **Settings**, **Devices & services**, **Add integration** and choose
   **Device Routines**. Setup has no fields.

Requires Home Assistant 2026.10.2 or newer.

## Documentation

- [User guide](docs/user-guide.md): the Schedule sensor, routines, skip and pause, the
  actions, triggers and conditions, supported devices, settings, removal,
  troubleshooting and limitations.
- [Product requirements](docs/PRD.md): what the integration does and why.
- [Technical specification](docs/TECH_SPEC.md): how it is built.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md): the build order and validation.
- [Decisions log](docs/decisions-log.md): choices made during implementation.

## FAQ

**Do my routines stop if I disable or remove the integration?** No. Each routine is an
ordinary automation, and Home Assistant runs it. With the integration disabled you lose
the device page controls and the Schedule sentences until you enable it again. Removing it
turns every routine into a normal automation by default (the On removal setting).

**Will it change my own automations?** No. It reads them to write the Schedule sentence
and never writes to an automation it did not create, even one with the same name, label
or category.

**Where are the routines stored?** In `automations.yaml`, as automations that use the
Device Routines blueprint. Git sees each change as an ordinary diff. Pauses are kept in
an entity, so pausing never touches the file.

**Can I edit a routine in the automation editor?** Yes. The blueprint form is a second
editor of the same settings, and the device page follows it. If an edit cannot work, the
routine turns off, nothing is overwritten, and Repairs offers the last valid settings.

**What happens after a restart?** A start or stop missed while Home Assistant was down is
applied within a minute of the start, unless you changed the device by hand. A Turn off
after countdown resumes with the time it had left.

**Which devices are supported?** Switches, lights, fans, input booleans, humidifiers,
climate (on and off only), media players (off only), vacuums, lawn mowers, covers, locks
(lock only) and valves. See [Supported devices](docs/user-guide.md#supported-devices).

**Why does the Schedule say "custom logic"?** The summary never guesses. Templates,
scripts, repeats and events in an automation are reported as custom logic instead of
being described wrongly.

## Privacy

- No cloud, no telemetry and no outbound calls. Everything runs inside your Home
  Assistant.
- The optional AI summary is off by default. It is used only if you pick an AI Task entity
  of your own in the options, and then it sends only the trigger, condition and action
  blocks of the automations the parser could not read, with entity ids and nothing else.
- No passwords, tokens or other secrets are stored.
- Diagnostics redact entity ids, device ids, device and area names, automation aliases
  and anything that looks like a token or an address before you download them.
- This repository is public and contains no data from any real home: documentation and
  tests use generic names only, and a privacy check runs on every commit.

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
