# Device Routines user guide

This guide grows with each release. Sections for routines, skip and pause, and removing
the integration arrive with the features they describe.

## Reading the Schedule sensor

Every device that at least one automation acts on gets a sensor called **Schedule** in the
Sensors card of its device page. The integration only reads automations to write it; it
never changes them.

### The state

The state is the next thing that will happen to the device, in at most 40 characters:

| State | Means |
| --- | --- |
| Off at 9:00 AM | The next timed action is today at 9:00 AM. |
| Start Wed 9:45 AM | The next timed action is on Wednesday. |
| Next: 9:45 AM | Two automations do opposite things at that moment, or the sentence would not fit; their conditions decide. |
| Off 60 min after it turns on | No timed action is coming; this is the first event driven line. |

A turned off automation never supplies the next action. A device with no automation
acting on it has no Schedule sensor at all.

### The attributes

`items` lists one entry per automation action on the device, timed ones first:

| Field | Content |
| --- | --- |
| `kind` | `automation` today; `routine` and `detached_routine` arrive with routines. |
| `automation` | The automation entity, so a card can link to it. |
| `alias` | The automation's name. |
| `summary` | The line, for example `Weekdays 9:45 AM: start (if 6 conditions pass)`. |
| `next_run` | When the line runs next, or null for event driven lines. |
| `source` | `parser` when the line was read from the automation, `none` when it could not be. |
| `enabled` | Whether the automation is turned on. |

`conflicts` lists pairs of items that drive the device in opposite directions in the same
minute within the next day. `paused_until` and `skipped_action` stay empty until routines
arrive.

### How lines are written

Lines are written by rules, never guessed. Each rule has a test, and the parser reads:

- Triggers: fixed times, times held by a date and time helper or a timestamp sensor, time
  patterns, sunrise and sunset with offsets, state and numeric state changes (with "for"),
  Home Assistant start and stop, calendar events, device triggers, and the purpose
  specific schedule, timer and vacuum triggers.
- Conditions: weekdays and time windows (folded into the line), state, numeric state and
  sun conditions, and/or/not, and purpose specific conditions such as "is docked" (counted
  as "if N conditions pass").
- Actions: turn on, turn off, toggle, start, return to dock, open, close, lock and unlock,
  with delays between actions on the same device ("off for 3 min, then on"), and choose or
  if branches keyed by trigger id.

Anything else (templates, scripts, repeats, waits, events) is never guessed. A line that
has some of it ends with "plus custom logic"; a line where nothing could be read says
"Automation: <name> (custom logic)".

### Daylight saving time

Times are local wall clock times and follow what Home Assistant's own time trigger does.
On the night clocks spring forward, a time that does not exist that night (2:30 AM in the
United States) does not run that day; the next run shown is the following day. On the
night clocks fall back, a time that happens twice runs twice, an hour apart.

### Where the sensor appears

The **Schedule sensor scope** setting (Settings, Devices and services, Device Routines,
Configure) chooses all devices with automations (the default), only devices with
routines, or nowhere. The **Time format** setting chooses 12 hour, 24 hour, or automatic,
which follows the country set in Home Assistant.

### Freshness

The sensor updates when automations are reloaded, turned on or off, when devices, areas,
floors or labels change, when a helper a time trigger reads changes, and at each next
run. Nothing polls.
