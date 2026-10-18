<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/jayanty/ha-device-routines/main/brand/dark_logo.png">
    <img alt="Device Routines" src="https://raw.githubusercontent.com/jayanty/ha-device-routines/main/brand/logo.png" height="64">
  </picture>
</p>

# Device Routines

[![CI](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/jayanty/ha-device-routines/actions/workflows/ci.yml)
[![HACS custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5)](https://hacs.xyz/docs/faq/custom_repositories/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/jayanty/ha-device-routines?include_prereleases)](https://github.com/jayanty/ha-device-routines/releases)

Device Routines adds start and stop times, run timers and a plain language schedule
summary to every Home Assistant device page, backed by real, clearly marked automations
that keep running even if the integration is removed.

It is made for the behaviors people otherwise write by hand, one automation per device:
run the air purifier from 5:00 PM to 9:00 AM, turn the bathroom fan off 60 minutes after
anyone turns it on, start the robot vacuum at 9:45 AM on weekdays, turn the patio light on
at sunset. And it answers, on every device page, what will happen to that device next,
whichever automation does it.

> **Status: 1.0.0 is in its last round of testing.** Everything below is built and proven
> in a real Home Assistant test harness and ships as the pre release `v1.0.0-beta.1`;
> `v1.0.0` follows once it has run on a real home. Version 0.1.0 brought the Schedule
> sensor, 0.3.0 the routines (first as the pre release `v0.3.0-beta.1`), and 1.0.0 adds
> sun times, Only when, conversion offers and the console. See [Status](#status).

## What it does

### A Schedule on every device page

Every device that any automation acts on gets a **Schedule** sensor. Its state is the
next thing that will happen to the device, as a short sentence: "Off at 9:00 AM",
"Start Wed 9:45 AM", "Paused until Sun 6:00 PM". Its attributes list each routine and
automation that controls the device, one line each ("Weekdays 9:45 AM: start (if 2
conditions pass)"), with its next run and any conflicts between them. Your own
automations are only read for this, never changed, and the summary never guesses:
templates, scripts and other logic it cannot read are labeled "custom logic".

### Routines, configured on the device page

Give a device routine controls by adding the `Routines` label on its page (or pick
devices in the options, from the suggestions after setup, or in the console). Its page then
gets Home Assistant's own time pickers, number boxes and switches. The words follow the
device, so a robot vacuum shows "Start at", a blind "Open at" and a lock "Lock at".

| Control | What it does |
| --- | --- |
| **Routine** | Turns the routine on and off. Off means nothing runs. |
| **Turn on at**, **Turn off at** | The times the device turns on and off. Either alone is fine; a window from 5:00 PM to 9:00 AM crosses midnight on its own. |
| **Days** | Every day, Weekdays, Weekends, Some days, or Weekly schedule. |
| **Turn off after** | Minutes after any turn on (by hand, app, voice or another automation) before the device turns off again. "Close after" on a blind or valve, "Lock after" on a lock. |
| **Skip next** | Skips the action the Schedule sentence shows next. A window start skips the whole window. |
| **Paused until** | A future time pauses the routine until then. |
| **Resume** | Ends a pause or a skip now. |
| **Manual override** | On while a change made by hand holds the device away from its schedule. |
| **Turn back on after** (advanced) | Keeps a device on: minutes after a turn off before it turns back on. |
| **Catch up after restart** (advanced) | After a restart or a reconnect, sets the device to the state its schedule expects now. |
| **Respect manual changes** (advanced) | A change by hand holds until the next scheduled time. |
| **Turn on timing**, **Turn off timing** (advanced) | Time, Sunrise or Sunset, each with a **sun offset** of up to three hours before or after. |
| **Routine controls** | On a device with several controllable entities, picks the one the routine drives. |

Advanced controls start disabled, so the page stays short until you need them. Each
change shows in the Schedule sentence within a second, and a combination that cannot
work is refused at the control with a message.

### Every routine option

| Option | Example | Where you set it |
| --- | --- | --- |
| Scheduled times | On at 5:00 PM, off at 9:00 AM, on weekdays | Device page |
| Some days | The same times on Monday, Wednesday and Friday | The routine's automation form or the console |
| Weekly schedule | Different blocks per day, edited in Home Assistant's own weekly schedule editor | Device page (Days), then the schedule helper |
| Sun times | On 15 minutes after sunset, off at 11:00 PM | Device page (advanced) |
| Turn off after | Off 60 minutes after anyone turns it on, surviving restarts | Device page |
| Turn back on after | Back on 10 minutes after it turns itself off | Device page (advanced) |
| Catch up after restart | A start missed while Home Assistant was down runs within a minute of the start; a one shot start such as a vacuum's runs only inside a late start window (15 minutes by default) | Device page (advanced), the window in the form |
| Respect manual changes | Turned on by hand inside an off window, the device stays on until the next scheduled time | Device page (advanced) |
| Pulse | A fan on since 6:00 AM is off from 8:00 AM to 8:03 AM, then on again | The routine's automation form |
| Only when | Start the vacuum only while guest mode is off, using Home Assistant's own condition editor | The routine's automation form |
| Skip, pause, resume, disable | Skip tonight; pause for two hours; turn the routine off | Device page, actions, console |
| Conversion offers | A hand written automation that does exactly what a routine does is offered as one in Repairs; confirming creates the routine and turns the original off, never deleting it | Repairs or the console |

### Built on plain automations

- **Home Assistant runs it.** Each routine is one normal automation built from a
  blueprint the integration ships. Traces, the automation list, the device page
  Automations card and git tracking of `automations.yaml` all work unchanged, and the
  routines keep running if the integration is disabled or removed.
- **Unmistakable.** Every routine carries its own id prefix, blueprint, alias, category,
  label and icon. The integration only ever writes to automations it created, and only
  the id and the blueprint together make an automation one of them.
- **Two editors, one setting.** The routine's blueprint form in the automation editor and
  the device page edit the same settings and always agree.
- **Survives restarts.** Run timers are timer helpers that keep their remaining time, and
  a missed start or stop is caught up when Home Assistant starts or the device returns.
- **Safe by refusal.** Nothing here will ever unlock a lock, open a garage door, gate or
  door, open a gas valve or disarm an alarm on a schedule. Those actions are refused in
  code, not merely hidden; closing and locking are fine.
- **Zero upkeep.** Setup has no fields. Renamed devices, a restored `automations.yaml`,
  missing helpers and removed devices heal on their own, and routines of devices that are
  gone are cleaned up after 30 days. Repairs asks only when a person has to decide, with a
  one click fix.

### The console

An admin only **Device Routines** panel in the sidebar shows every routine of the house
on one page, in three views:

- **Routines**: every routine with its device, area, Schedule sentence, status, next action
  and pause. Skip next, pause, resume, enable and disable per row or for a selection; edit
  settings inline; opt devices in and out; convert the automations that can become
  routines.
- **Today**: every action planned for a day, the routines' and the other automations'
  alike, grouped by area and ordered by time, with conflicts highlighted.
- **Settings**: every global setting, the maintenance actions with a preview first, and
  Health.

The console does nothing the device page cannot: every button calls the same service
layer.

### Dashboards, scripts and automations

- **Actions** `device_routines.skip_next`, `pause`, `resume`, `enable` and `disable` take a
  device, area, floor, label or entity, so one dashboard button can skip tonight for a
  whole room. `device_routines.maintenance` runs the maintenance actions.
- **Triggers** (Routine action skipped, Routine paused, Routine resumed) and
  **conditions** (Routine is paused, Routine is active) appear in the automation editor's
  own pickers.
- A hub device holds a **Routines** sensor listing every routine for a markdown card, a
  **Problem** sensor, a **Health** sensor and a **Clean up now** button.
- Everything the device page can do is also a [WebSocket command](docs/api.md) for custom
  cards and tools.

### Supported devices

| Domain | Start | Stop | Options |
| --- | --- | --- | --- |
| Switch, light, fan, input boolean, humidifier | Turn on | Turn off | All |
| Climate | Turn on | Turn off | Times, Days, Turn off after |
| Media player | | Turn off | Turn off at, Days, Turn off after |
| Vacuum, lawn mower | Start (only from the dock, by default) | Return to dock | Times, Days |
| Cover | Open (never a garage door, gate or door) | Close | Times, Days, Close after |
| Lock | | Lock (never unlock) | Lock at, Days, Lock after |
| Valve | Open (never a gas valve) | Close | Times, Days, Close after |

A device qualifies when it has an entity in one of these domains that is not a
configuration or diagnostic entity. Entities without a device cannot have a routine.

## Install

Requires Home Assistant 2026.10.2 or newer.

### Through HACS

Device Routines is distributed through [HACS](https://hacs.xyz/) as a custom repository
until it reaches the HACS default list.

1. In Home Assistant open HACS, then the three dot menu, then **Custom repositories**.
2. Add `https://github.com/jayanty/ha-device-routines` with the category **Integration**.
3. Find **Device Routines** in HACS and download it. To try a pre release such as
   `v1.0.0-beta.1`, let HACS show pre releases when you download it.
4. Restart Home Assistant.
5. Open **Settings**, **Devices & services**, **Add integration** and choose
   **Device Routines**. Setup has no fields; one optional screen offers routine controls
   for the devices your automations already switch at set times.

HACS shows each new release as an update. Install it and restart Home Assistant; the
first start of a new version migrates the routines by itself. Reload the browser page
afterwards to load the new console.

### By hand

1. Download `device_routines.zip` from the
   [latest release](https://github.com/jayanty/ha-device-routines/releases).
2. In your Home Assistant configuration folder (the one with `configuration.yaml`), create
   `custom_components/device_routines`.
3. Unpack the zip into that folder, so that `manifest.json` ends up at
   `custom_components/device_routines/manifest.json`.
4. Restart Home Assistant, then add the integration as in step 5 above.

To update by hand, replace the folder's contents with the new zip's and restart.

### Your first routine

1. Open a device page, for example a living room fan's, and add the label **Routines**.
2. Set **Turn on at** to 5:00 PM and **Turn off at** to 11:00 PM.
3. The Schedule sensor reads "On at 5:00 PM". That is the whole setup: the routine is the
   automation "Routine: Living room fan" in the automation list.

## FAQ

**Do my routines stop if I disable or remove the integration?** No. Each routine is an
ordinary automation, and Home Assistant runs it. With the integration disabled you lose
the device page controls and the Schedule sentences until you enable it again. Removing
it turns every routine into a normal automation by default (the On removal setting).

**Will it change my own automations?** No. It reads them to write the Schedule sentence
and never writes to an automation it did not create, even one with the same name, label
or category. The one exception is a conversion you confirm yourself, which turns the
original off and labels it `Replaced by routine`; turning it back on undoes that.

**Where are the routines stored?** In `automations.yaml`, as automations that use the
Device Routines blueprint. Git sees each change as an ordinary diff. Pauses and skips
live in an entity, so they never touch the file.

**Can I edit a routine in the automation editor?** Yes. The blueprint form is a second
editor of the same settings, and the device page follows it. Pulse, Only when, the late
start window and the day set of Some days are set there. If an edit cannot work, the
routine turns off, nothing is overwritten, and Repairs offers the last valid settings.

**What happens after a restart?** A start or stop missed while Home Assistant was down is
applied within a minute of the start, unless you changed the device by hand. A Turn off
after countdown resumes with the time it had left.

**Can a routine follow sunrise and sunset?** Yes. Enable the device's advanced Turn on
timing or Turn off timing control, choose Sunrise or Sunset, and set an offset of up to
three hours before or after.

**Can I skip just tonight, or pause a whole room?** Skip next on the device page skips the
next action; for a window start it skips the whole window. The pause action takes an
area, floor or label, so a dashboard button can pause every routine in a room.

**Is there a vacation mode?** Not in this version. Pause the routines of an area or a label
until a date instead.

**Can I see every routine in one place?** Yes: the console in the sidebar, the automation
list filtered by the `Routines` label or the `Device Routines` category, or the hub's
Routines sensor on a dashboard.

**Which devices are supported?** Switches, lights, fans, input booleans, humidifiers,
climate (on and off only), media players (off only), vacuums, lawn mowers, covers, locks
(lock only) and valves. See [Supported devices](#supported-devices).

**Why does the Schedule say "custom logic"?** The summary never guesses. Templates,
scripts, repeats and events in an automation are reported as custom logic instead of
being described wrongly. An optional AI summary, off by default, can describe them with
an AI Task entity you choose.

**Why minutes and not seconds?** Routines are for schedules people set by hand: times are
whole minutes and durations are minutes, up to 1440.

## Privacy

- No cloud, no telemetry and no outbound calls. Everything runs inside your Home
  Assistant.
- The optional AI summary is off by default. It is used only if you pick an AI Task entity
  of your own in the options, and then it sends only the trigger, condition and action
  blocks of the automations the parser could not read, with entities named by their ids,
  devices, areas, floors and labels replaced by numbered placeholders, and no states,
  names, aliases or descriptions.
- No passwords, tokens or other secrets are stored.
- Diagnostics redact entity ids, device ids, device and area names, automation aliases
  and anything that looks like a token or an address before you download them, and the
  bug report template asks for those redacted diagnostics only.
- This repository is public and contains no data from any real home: no entity ids,
  device ids, device, area or floor names, automation text, addresses, host names or
  tokens. Documentation and examples use generic names only (a living room fan, a robot
  vacuum), test fixtures from a real installation are anonymized by a tool before they are
  committed, and a privacy check runs on every commit and in CI.

## Status

| Version | What it brought | Released as |
| --- | --- | --- |
| 0.1.0 | The Schedule sensor on every device an automation acts on | `v0.1.0` |
| 0.3.0 | Routines: the device page controls, run timers, catch up, manual changes, skip and pause, weekly schedules, keep alive, pulse, the actions, triggers and conditions, conflicts, the AI summary, the WebSocket API | `v0.3.0-beta.1`, then `v0.3.0` |
| 1.0.0 | Sun times, Only when, conversion offers, the console | `v1.0.0-beta.1`, then `v1.0.0` |

Each beta follows its test harness record; each full release follows a run on a real
home. After 1.0.0 the plan is listing in the HACS default list and the Home Assistant
brands repository. A calendar view, which would also bring vacation handling, is a
candidate for later. The [changelog](CHANGELOG.md) lists every change.

## Documentation

- [User guide](docs/user-guide.md): installing, the Schedule sensor, routines, skip and
  pause, weekly schedules, sun times, Only when, conversions, the console, the actions,
  triggers and conditions, supported devices, settings, removal, troubleshooting, privacy,
  limitations and an FAQ.
- [WebSocket API](docs/api.md): every command, payload and event, for custom cards and
  tools.
- [Product requirements](docs/PRD.md): what the integration does and why.
- [Technical specification](docs/TECH_SPEC.md): how it is built.
- [Implementation plan](docs/IMPLEMENTATION_PLAN.md): the build order and validation.
- [Decisions log](docs/decisions-log.md): choices made during implementation.
- [Publication](docs/publication.md): the brands and HACS default submissions, prepared.

## Development

The repository is public and generic: it never contains data from a real home. See
`CLAUDE.md` for the engineering rules and [frontend/README.md](frontend/README.md) for the
console.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest -m "not live" --cov
.venv/bin/python -m tools.make_brand --check
```

## License

[MIT](LICENSE). The logo's words are set in Aileron Regular, released under CC0 1.0.
