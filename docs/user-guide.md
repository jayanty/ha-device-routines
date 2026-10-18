# Device Routines user guide

Device Routines puts start and stop times, run timers and a plain language Schedule
sentence on your device pages. Each routine is a normal Home Assistant automation built
from a blueprint the integration ships, so Home Assistant runs it, traces it and keeps it
in `automations.yaml` like any other automation.

It is made for the behaviors people otherwise write by hand, one automation per device:

- Run the air purifier from 5:00 PM to 9:00 AM.
- Turn the bathroom fan off 60 minutes after anyone turns it on.
- Start the robot vacuum at 9:45 AM on weekdays, only from its dock.

And it answers, on every device page, what will happen to that device next, whichever
automation does it.

Every example below uses made up devices (a living room fan, a desk lamp, a robot
vacuum) and is a routine the project's test suite runs. Routines ship in version 0.3.0;
version 0.1.0 has the Schedule sensor only.

- [Reading the Schedule sensor](#reading-the-schedule-sensor)
- [Giving a device a routine](#giving-a-device-a-routine)
- [Skip, pause and resume](#skip-pause-and-resume)
- [Weekly schedules](#weekly-schedules)
- [Turn back on after](#turn-back-on-after)
- [Pulse](#pulse)
- [Sun times](#sun-times)
- [Only when](#only-when)
- [Converting automations](#converting-automations)
- [What the managed automation looks like](#what-the-managed-automation-looks-like)
- [If you edit the automation yourself](#if-you-edit-the-automation-yourself)
- [When the integration is off](#when-the-integration-is-off)
- [Daylight saving nights](#daylight-saving-nights)
- [Dashboards and scripts](#dashboards-and-scripts)
- [Console](#console)
- [Supported devices](#supported-devices)
- [Settings](#settings)
- [Removing the integration](#removing-the-integration)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

## Reading the Schedule sensor

Every device that at least one automation acts on gets a sensor called **Schedule** in the
Sensors card of its device page. The integration only reads hand written automations to
write it; it never changes them.

### The state

The state is the next thing that will happen to the device, in at most 40 characters:

| State | Means |
| --- | --- |
| Off at 9:00 AM | The next timed action is today at 9:00 AM. |
| Start Wed 9:45 AM | The next timed action is on Wednesday. |
| Next: 9:45 AM | Two automations do opposite things at that moment, or the sentence would not fit; their conditions decide. |
| Off 60 min after it turns on | No timed action is coming; this is the first event driven line. |
| Skipped, on Thu 5:00 PM | The device's routine skipped its next action; this is the next one that will really run. |
| Paused until Sun 6:00 PM | The device's routine is paused until then. |
| Routine off | The device's routine is turned off, or cannot run (see [Troubleshooting](#troubleshooting)). |
| Automation off, Automations off | Every automation acting on the device is turned off, so nothing is planned; a routine that is off reads Routine off instead. |

A turned off automation never supplies the next action. A time that follows sunrise or
sunset reads to the whole minute ("On at 7:26 AM"), although the action runs at the
second the sun gives it; a time an automation writes with seconds keeps them. A device with no automation
acting on it has no Schedule sensor at all. A routine's pause or skip never changes the
lines of hand written automations on the same device.

### The attributes

`items` lists one entry per automation action on the device. The routine comes first,
then timed lines, then event driven ones:

| Field | Content |
| --- | --- |
| `kind` | `routine` for the device's routine, `automation` for any other automation, `detached_routine` for a former routine someone took control of. |
| `automation` | The automation entity, so a card can link to it. |
| `alias` | The automation's name. |
| `summary` | The line, for example `Weekdays 9:45 AM: start (if 6 conditions pass)`. A routine reads like `Weekdays 5:00 PM: on, Weekdays 11:00 PM: off`. |
| `next_run` | When the line runs next, or null for event driven lines. |
| `source` | `parser` when the line was read from the automation, `none` when it could not be. |
| `enabled` | Whether the automation is turned on. |

`conflicts` lists pairs of items that drive the device in opposite directions in the same
minute within the next day, and actions of other automations that go against the
routine's window (an off while it should be on, an on while it should be off), a window
that follows sunrise or sunset included. A change to the routine shows its conflicts at
once, before it is written. `paused_until` holds the end of the routine's pause or skip,
and `skipped_action` names the action Skip next skipped; both are empty otherwise.

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

### Daylight saving time in sentences

Times are local wall clock times and follow what Home Assistant's own time trigger does.
On the night clocks spring forward, a time that does not exist that night (2:30 AM in the
United States) does not run that day; the next run shown is the following day. On the
night clocks fall back, a time that happens twice runs twice, an hour apart.

### Where the sensor appears

The **Schedule sensor scope** setting chooses all devices with automations (the
default), only devices with routines, or nowhere. The **Time format** setting chooses 12
hour, 24 hour, or automatic, which follows the country set in Home Assistant. Both are on
the settings page (see [Settings](#settings)).

### Freshness

The sensor updates when automations are reloaded, turned on or off, when devices, areas,
floors or labels change, when a helper a time trigger reads changes, when a routine
changes, and at each next run. Nothing polls.

## Giving a device a routine

### Choosing devices

Nothing has routine controls until you ask for them. Any of these gives a device its
controls, and they stay in sync:

- **The `Routines` label.** Open the device page and add the label `Routines` (the
  integration creates it, with a calendar clock icon). Removing the label takes the
  controls away again. The label is the visible truth: every other way applies it.

- **The options.** Settings, Devices and services, Device Routines, Configure, then
  **Devices with routines**: a device picker that lists only devices with something a
  routine can drive.
- **The suggestions.** Right after setup, and again from the options, one optional screen
  lists the devices that already have time based automations, all unchecked. Tick the
  ones you want, or skip it.

A device qualifies when it has an entity in a [supported domain](#supported-devices)
that is not a configuration or diagnostic entity. Entities without a device are not
supported.

### The controls

The device page gets these controls. They are Home Assistant's own time pickers, number
boxes and switches; labels follow the device, so a robot vacuum shows "Start at" and a
blind shows "Open at".

| Control | Card | Shown | What it does |
| --- | --- | --- | --- |
| Routine | Configuration | Yes | Turns the routine on and off. Off means nothing runs. It mirrors the automation, so turning the automation off in the automation list turns this off too. |
| Turn on at | Configuration | Yes | The time the device turns on. Setting it creates the routine. |
| Turn off at | Configuration | Yes | The time the device turns off. Either time alone is fine. |
| Days | Configuration | Yes | Every day, Weekdays, Weekends, Some days or Weekly schedule. |
| Turn off after | Configuration | Where the device supports it | Minutes after any turn on before the device turns off again; 0 is off. It reads "Close after" on a blind or a valve and "Lock after" on a lock. |
| Turn back on after | Configuration | No, advanced | Minutes after a turn off before the device turns back on; 0 is off. See [Turn back on after](#turn-back-on-after). |
| Catch up after restart | Configuration | No, advanced | On by default. See [After a restart](#after-a-restart-catch-up). |
| Respect manual changes | Configuration | No, advanced | On by default. See [Manual changes](#manual-changes). |
| Skip next | Controls | Yes | Skips the action the Schedule sentence shows next. |
| Paused until | Controls | Yes | Empty unless paused. A future time pauses the routine. |
| Resume | Controls | Yes, available while paused or skipping | Ends a pause or a skip now. |
| Manual override | Diagnostic | Yes | On while a change made by hand holds the device away from its schedule. |
| Routine controls | Configuration | Only with several candidates | Picks which entity the routine drives when the device has more than one. |

Advanced controls are created disabled. To use one, open the device page, show the
entities that are hidden, and enable it.

Home Assistant's time control has no way to clear a time. To remove Turn on at or Turn off
at, clear it in the routine's automation form.

The Schedule sensor confirms every change within a second, in words. The write to
`automations.yaml` follows one second after your last change, so setting three values in
a row is one write. A combination that cannot work is refused with a message and the
control goes back to its old value: the same start and stop time, Turn off after together
with Turn back on after, a start time on a device that cannot be turned on (a lock), or a
time while Days is Weekly schedule.

Example: a living room fan with **Turn on at** 5:00 PM and **Turn off at** 9:00 AM turns
on at 5:00 PM and off at 9:00 AM the next morning. During the day its Schedule reads "On
at 5:00 PM".

### Days

Days limits the scheduled times; run timers apply every day.

| Days | Runs on |
| --- | --- |
| Every day | Every day. |
| Weekdays | Monday to Friday. |
| Weekends | Saturday and Sunday. |
| Some days | A day set you choose in the routine's automation form, or through the WebSocket API (the device page select shows Some days). A day set chosen on its own means Some days. |
| Weekly schedule | The blocks of a weekly schedule helper instead of the two times. See [Weekly schedules](#weekly-schedules). |

A window that crosses midnight belongs to the day it starts. With Weekdays, 5:00 PM to
9:00 AM: Friday's window runs until Saturday 9:00 AM, Saturday and Sunday stay off, and
on Monday at 8:00 AM the device is off, because Sunday did not start a window.

### Turn off after

Turn off after counts down from any turn on that the schedule did not make: by hand, from
the app, by voice or from another automation. Example: a desk lamp with Turn off after
30, turned on at 10:00 AM, turns off at 10:30 AM.

- Turning the device off cancels the countdown; turning it on again starts a new one.
- The countdown is a timer helper (`timer.routine_desk_lamp`), so it survives a restart:
  restarted at 10:20 AM, the lamp still turns off at 10:30 AM.
- Inside a window that has a Turn off at, it does not apply: the window decides.
- After a Turn on at with no Turn off at, it does apply: Turn on at 7:00 AM with Turn off
  after 30 means "on at 7:00 for 30 minutes", even if the device was already on.

### After a restart: catch up

With **Catch up after restart** on (the default), when Home Assistant starts, and when the
device comes back from unavailable for 10 seconds, the routine sets the device to the
state its schedule expects now. Example: a 5:00 PM on time, Home Assistant down from 4:55
PM to 5:10 PM: the fan is on within a minute of the start. A device that was unreachable
at 5:00 PM is switched when it returns.

A start with no stop (a robot vacuum that starts at 9:45 AM) is caught up only inside the
late start window, 15 minutes by default: down from 9:40 AM to 9:50 AM, the vacuum starts
at 9:50 AM; back at 10:05 AM, it waits for tomorrow. The window is in the routine's
automation form (Behavior, Late start window; 0 turns it off).

New routines take the late start window from the **Late start window** setting.

Every on and off checks the device first, so catch up running twice changes nothing.

### Manual changes

With **Respect manual changes** on (the default), a change made by hand (a wall switch,
the app, a dashboard, a voice assistant) that leaves the device in a state the schedule
did not ask for turns **Manual override** on. While it is on, catch up and Turn back on
after leave the device alone. The next scheduled time always runs and clears it.
Turning Manual override off yourself hands the device back to the schedule at once. Its
`last_change_source` attribute says what changed the device last: `automation`, `user`
or `device`.

Example: the fan's window is 5:00 PM to 9:00 AM. You turn it on by hand at noon, and Home
Assistant restarts at 12:30 PM: the fan stays on, with Manual override on. At 5:00 PM the
routine takes over and the override clears.

With Respect manual changes off, nothing is held: the next catch up (a restart or a
reconnect) puts the device back to the schedule's state.

Changes made by other automations and scripts never count as manual.

## Skip, pause and resume

Every "not now" is one stored value per device, **Paused until**, so a restart never loses
it and the routine checks a single rule. Skip and pause act on routines only; hand
written automations on the same device keep running.

### Skip next

Skip next skips the action the Schedule sentence shows next:

- **A window start:** the whole occurrence is skipped, start and end. Example: Wednesday at
  3:00 PM with a 5:00 PM to 9:00 AM window, Skip next leaves the fan off tonight; the
  sentence reads "Skipped, on Thu 5:00 PM" and Paused until is Thursday 9:01 AM.
- **A window end:** the device stays as it is until the following scheduled action.
  Example: at 8:00 PM inside a 5:00 PM to 11:00 PM window, Skip next keeps the fan on past
  11:00 PM; Manual override turns on so nothing turns it off early, and tomorrow's 5:00 PM
  start clears it.
- **A running countdown:** the timer is cancelled and the device stays as it is.

Pressing Skip next again extends the skip to the following action. Skip next is
unavailable (reason `nothing_to_skip`) when nothing is scheduled; a running countdown
counts, so Skip next can keep a device on this time. Resume is unavailable (reason
`not_paused`) unless the routine is paused or skipping.

### Pause until

Set **Paused until** to a future time. A time in the past is refused with a message.
While paused, no scheduled action runs and no countdown starts; a countdown that was
running pauses and later continues with the time it had left. You can still use the
device by hand, and that does not turn Manual override on. The sentence reads "Paused
until Sun 6:00 PM".

When the pause ends, the routine catches up if Catch up after restart is on. Example: the
fan's window is 5:00 PM to 11:00 PM and it is paused until 6:30 PM: it stays off at 5:00
PM, and at 6:30 PM it turns on.

### Resume

**Resume** ends a pause or a skip now and then catches up the same way. It also clears a
Manual override that a skip set. A new pause replaces a skip.

### The Routine switch

Turning the **Routine** switch off stops everything: no scheduled action, no countdown,
no catch up. A Paused until value is kept, and applies again if you turn the routine
back on before it ends. The sentence reads "Routine off".

The same four things are actions you can call for a whole room, floor or label at once;
see [Actions](#actions).

## Weekly schedules

Set **Days** to **Weekly schedule** when the times differ by day. The integration creates
a schedule helper named after the device ("Living room fan routine",
`schedule.routine_living_room_fan`), labels it `Routines` and links it to the routine.
Turn on at and Turn off at become unavailable, because the blocks decide. Edit the blocks
in Home Assistant's own weekly editor: Settings, Devices and services, Helpers, then the
schedule.

The device turns on when a block starts and off when it ends. Example: blocks Monday 5:00
PM to 10:00 PM and Tuesday 8:00 AM to 9:00 AM turn the fan on and off at exactly those
times. Two blocks that meet at midnight (Monday 10:00 PM to midnight, Tuesday midnight to
2:00 AM) keep the device on across midnight without a blip.

Catch up, Manual override, pauses and Turn off after treat a block like a window. If the
schedule helper is deleted, the integration creates it again with the same entity id, but
the new one is empty: a Repairs issue asks you to enter the blocks once more.

## Turn back on after

Turn back on after keeps a device on: after any turn off the routine did not make, it
turns the device back on after N minutes. Example: a fan that turns itself off at 2:00 PM
is back on at 2:10 PM with Turn back on after 10.

- It never fires during a scheduled off period: with a window, it acts only inside it, and
  its control on the device page is unavailable (reason `schedule_off`) while the window or
  the weekly schedule says off.
- Turning the device on yourself cancels the countdown.
- The countdown survives a restart, like Turn off after.
- It wins over Respect manual changes by design, because undoing offs is its purpose. To
  stop it, turn the Routine off or pause it.
- A routine has either Turn off after or Turn back on after, never both.

## Pulse

A pulse switches the device to the opposite state for a few minutes at a set time, then
back, but only if the device has been steady for a while. Example: a fan on since 6:00
AM, with a pulse at 8:00 AM, is off from 8:00 AM to 8:03 AM and then on again. A fan
that is off gets a three minute on instead.

Pulse is set in the routine's automation form, not on the device page: open the routine
from the device page's Automations card, then Advanced: **Use pulse**, **Pulse at**,
**Pulse length** (3 minutes by default) and **Pulse only after steady for** (5 minutes by
default; a device that changed more recently is left alone). A pulse is skipped while the
routine is paused. If Home Assistant restarts during the pulse, its second half is lost;
a routine with a window puts the device back to the window's state at startup.

## Sun times

Turn on at and Turn off at can follow the sun instead of the clock. Each time has two
advanced controls, created disabled like the others (show the hidden entities on the
device page and enable them):

| Control | What it does |
| --- | --- |
| Turn on timing, Turn off timing | Time, Sunrise or Sunset. Time uses the time control; Sunrise and Sunset follow the sun at the device's home location, every day anew. |
| Turn on sun offset, Turn off sun offset | Minutes from sunrise or sunset, from -180 to 180; negative is before the event. |

The words follow the device, as the times do: a robot vacuum shows "Start timing" and
"Return to dock timing", a blind "Open timing", a lock "Lock timing" and "Lock sun
offset". A lock has no start, so it has no start timing either; "Lock at sunset" is fine.

While a side follows the sun its time control is unavailable (reason `sun_bound`), and
while it is a time its offset control is (reason `time_bound`): each shows the one value
that side uses. Setting the timing back to Time leaves that side without a time until you
choose one. In the routine's automation form the same choice is "Turn on at, kind" and
"Turn on at, sun offset" (as `HH:MM:SS`, with a leading minus before the event).

Example: a patio light with **Turn on timing** Sunset, **Turn on sun offset** 15 and
**Turn off at** 11:00 PM turns on a quarter of an hour after sunset and off at 11:00 PM.
Its Schedule line reads "Sunset + 15 min: on, 11:00 PM: off", and before the light
turns on its state names the moment of today's sunset plus the offset, to the whole
minute.

- **Across midnight.** Sunset to sunrise is a window across midnight, which belongs to the
  day it starts, as for times: with Weekdays, Friday's sunset turns the light on and
  Saturday's sunrise turns it off. Whether a window crosses midnight is decided once, by
  reading sunrise as 6:00 AM and sunset as 6:00 PM plus their offsets: sunset to sunrise
  crosses, sunrise to sunset does not, 10:00 PM to sunrise crosses, sunset to 11:00 PM does
  not. A fixed time that the sun passes over in the course of the year keeps that order:
  sunset to 8:00 PM is a window on the same day, so on a summer evening whose sunset is
  after 8:00 PM it does not run.
- **Everything else works as for a time.** Catch up after a restart, Manual override, Skip
  next (a sunset start skips its sunrise end too), Pause until, Days and the Routine switch
  treat a sun time like a time of day.
- **A day without a sunrise or sunset** (near the poles) runs nothing for that side that
  day.
- **Daylight saving.** The offset is added to the day's sunrise or sunset on the wall
  clock.
- **Weekly schedule.** Setting Days to Weekly schedule drops the sun times, as it drops the
  times; the schedule's blocks give the times.

## Only when

**Only when** adds Home Assistant conditions that must hold for the routine to turn the
device on: guest mode is off, the battery is above 95 percent, nobody is home. It is set
in the routine's automation form, under Advanced, with Home Assistant's own condition
editor; the device page has no control for it.

The conditions are checked whenever the routine would turn the device on, start it or open
it: Turn on at (a time or the sun), the start of a weekly schedule block, a catch up after
a restart or at the end of a pause, Turn back on after and the pulse. They never hold back
a turn off: Turn off at and Turn off after always run. A start the conditions block does
not run, and fires no skipped action event: the device stays as it is, and the next start
whose conditions pass runs as usual.

Example: a robot vacuum with **Start at** 9:45 AM on Weekdays and Only when guest mode is
off stays docked on a weekday morning while guests are over. The Schedule line counts the
conditions on the actions they gate: "Weekdays 9:45 AM: start (if 1 condition passes)";
with two conditions it reads "(if 2 conditions pass)".

## Converting automations

A hand written automation that does exactly what a routine does can become one. Device
Routines finds them by itself and offers each one once, in Repairs ("Fan evening can
become a routine on Living room fan") and in the console's Routines view. The offer shows
both summaries side by side, for example "5:00 PM: on, 11:00 PM: off" for the automation
and the same line for the routine.

Two shapes are exact:

- **Scheduled times.** Two time triggers at whole minutes, one turning one entity of the
  device on and the other turning it off (a choose or an if on the trigger ids, as the
  automation editor builds it), with no condition or only weekdays. A window across
  midnight counts only every day, because a routine ends a window the day after each start
  day while the automation would end it on its own weekdays.
- **Turn off after.** One state trigger on a switch, light, fan, input boolean or
  humidifier, to on (from off, or with no from), held a whole number of minutes from 1 to
  1440, no condition, and one action that turns the same entity off.

The action may name its entity as its target, on the step or in its data; the empty
`data: {}` and `metadata: {}` the editor adds are fine, anything else in them is not.

Nothing else is offered, so a routine never drops what an automation does. No offer for
an automation that also notifies, sets a scene, waits, sets a brightness, uses a template
or variables, runs at seconds or at an entity's time, uses sun times, has other
conditions, catches up at start, or acts on a second device; none for an automation that
is turned off; none for a device that already has a routine, its own or one taken over;
none for an action a routine refuses, such as opening a garage door; none for an
automation without an id.

**Converting.** Open the issue in Settings, System, Repairs. The first step shows the two
summaries; submit, then confirm. Confirming:

1. Gives the device routine controls if it had none (the `Routines` label) and creates its
   routine with the automation's times or duration, and with your defaults for catch up,
   manual changes and the late start window.
2. Turns the original automation off.
3. Adds the label **Replaced by routine** to the original.

The original is never edited or deleted, and it gets none of the routine markers. If the
offer ended before you confirmed (you turned the automation off or changed it, or the
device got a routine), or the routine could not be saved, nothing is converted and the
original stays as it was.

**Undo.** Turn the original back on. The routine stays on the device until you clear its
settings on the device page or remove the device's `Routines` label; while the device has
a routine, the offer does not come back.

An offer is a suggestion, not a problem: unlike the other Repairs issues it leaves the
hub's Problem sensor off. Ignore it in Repairs to keep the automation as it is, or turn
**Offer to convert matching automations** off in the settings, which clears every offer.

## What the managed automation looks like

Each routine is one automation, and you can tell it apart from your own at a glance:

| Where you look | What you see |
| --- | --- |
| Automation list | The alias `Routine: Living room fan`, the calendar clock icon, the category Device Routines and the label Routines |
| Its settings | The id `device_routines_` followed by 12 hexadecimal characters, the entity id `automation.routine_living_room_fan`, and the device's area |
| The editor | The blueprint form "Device routine (managed by Device Routines)" and the description "Managed by Device Routines. Change it on the Living room fan device page or in this form. Take control to turn it into a normal automation." |
| `automations.yaml` | One entry that uses the blueprint `device_routines/device_routine.yaml`, its settings as blueprint inputs |

A trimmed entry looks like this:

```yaml
- id: device_routines_0123456789ab
  alias: "Routine: Living room fan"
  description: >-
    Managed by Device Routines. Change it on the Living room fan device page or in this
    form. Take control to turn it into a normal automation.
  use_blueprint:
    path: device_routines/device_routine.yaml
    input:
      target_entity: switch.living_room_fan
      on_action: switch.turn_on
      off_action: switch.turn_off
      on_time_enabled: true
      on_time: "17:00:00"
      off_time_enabled: true
      off_time: "09:00:00"
      crosses_midnight: true
      # ... the other inputs, each with its value
```

Only the id and the blueprint make an automation a routine. An automation with the same
alias, label or category is still yours, and the integration never writes to it.
Duplicating a routine in the editor gives a normal automation too.

The routine may come with two helpers, both labeled `Routines`:

| Helper | When |
| --- | --- |
| `timer.routine_living_room_fan` | Turn off after or Turn back on after is set |
| `schedule.routine_living_room_fan` | Days is Weekly schedule |

The blueprint also reads two of the device's own Device Routines entities, Manual
override (`switch.living_room_fan_manual_override`) and Paused until
(`datetime.living_room_fan_paused_until`).

Pausing or skipping never rewrites `automations.yaml`, so git only sees real changes. The
**Routines** label page and the automation list filtered by the label or the category show
every routine and helper in one place.

## If you edit the automation yourself

The device page and the automation's blueprint form are two editors of the same settings.

| You | The integration |
| --- | --- |
| Change an input in the blueprint form | The device page controls follow. |
| Edit the entry in `automations.yaml` and reload automations | The same as a form edit. |
| Turn the automation off or on | The Routine switch follows. |
| Save something a routine cannot run (an unknown input, a missing one, a refused action) | Turns the routine off, overwrites nothing, and raises a Repairs issue that can restore the last valid settings. Correcting the form brings the routine back. |
| Delete the automation | Treats it as clearing the routine: the settings reset and the device keeps its controls. No Repairs issue. |
| Take control (Home Assistant's "Take control" in the editor) | The automation becomes a normal automation and is never touched again. The device page controls show unavailable, the Schedule lists it as "Detached routine", and a Repairs issue offers to create a new routine. |
| Restore `automations.yaml` from git | The integration rebuilds its index from the id and the blueprint of each entry; the device pages follow the restored settings. |
| Change the alias | The alias stays yours: it no longer follows device renames. |
| Remove the category, label or icon | Allowed; the automation stays a routine. |
| Edit the installed blueprint file | Left as it is; routines keep running on your edit. A Repairs issue offers to restore the shipped file. |

Renaming the device renames the alias while it is still the generated one. Renaming the
target entity id rewrites the input and reloads the automation. Moving the device to
another area moves the automation too, while **Put routines in the device's area** is on.

Writing `automations.yaml` drops comments and anchors in it, exactly as the automation
editor does. Keep notes in the automation's description instead.

## When the integration is off

Home Assistant runs the routines; the integration only configures them. With Device
Routines disabled, or removed with On removal set to keep, every routine still turns
devices on and off on time, runs its countdowns, catches up after a restart or a
reconnect, keeps devices alive and pulses.

What needs the integration:

- The device page controls, the Schedule sensors and the hub sensors.
- Manual override: no new override is set, and an existing one reads as off, so routines
  behave as plain schedules.
- Computing Skip next. A pause that already exists still holds and still ends; the catch
  up at its exact end waits for the routine's next scheduled time instead.
- Catching up a countdown that ran out while Home Assistant was down. Home Assistant
  finishes such a timer while it starts, before any automation listens, so nothing sees
  the finish. With the integration loaded, it reads the timer's state from before the
  shutdown and runs the routine's countdown action once Home Assistant has started.
  Without it, a Turn off after that ran out during the restart leaves the device on, and
  a Turn back on after leaves it off, until something else changes the device.

## Daylight saving nights

Times are local wall clock times and routines do exactly what Home Assistant's time
trigger does:

- **Spring forward:** a time inside the skipped hour does not run that night. A routine
  from 2:30 AM to 6:00 AM in the United States does not start on 2026-03-08; it runs
  normally the next night.
- **Fall back:** a time inside the repeated hour runs twice, an hour apart. Every on and
  off checks the device first, so the second run changes nothing, but a pulse at a
  repeated time pulses twice.

## Dashboards and scripts

### Actions

| Action | Does | Fields |
| --- | --- | --- |
| `device_routines.skip_next` | Skip next | target |
| `device_routines.pause` | Pause until a time, or for a duration | target, and exactly one of `until` (a date and time; one without an offset is local time) or `for` (a duration) |
| `device_routines.resume` | Resume | target |
| `device_routines.enable` | Turn the routine on, like its Routine switch | target |
| `device_routines.disable` | Turn the routine off, like its Routine switch | target |
| `device_routines.maintenance` | Run a maintenance action | `action`: `clean_up_now`, `rebuild_index`, `reinstall_blueprint` or `refresh_summaries`; `dry_run` (optional) only reports what would change |

The target is a device, an area, a floor, a label or an entity: an entity a routine can
drive, or a routine's own automation. Devices without a routine are ignored and listed in the response, so a label that covers a fan with a
routine and a lamp without one skips the fan and reports the lamp. A target with no
routine at all is an error, and so is a call while Device Routines is not loaded.

The response is optional. `results` has one entry per routine with `device_id`,
`device_name`, `action`, `paused_until`, `skipped_action` and `next_action`; `ignored`
names every target left out with its `kind` and a `reason`. The maintenance action answers
with what it changed, or with a dry run, what it would change.

A dashboard button that skips the next run of every routine labeled Evening:

```yaml
type: button
name: Skip tonight
icon: mdi:calendar-remove
tap_action:
  action: perform-action
  perform_action: device_routines.skip_next
  target:
    label_id: evening
```

A script that pauses the living room's routines for two hours:

```yaml
sequence:
  - action: device_routines.pause
    target:
      area_id: living_room
    data:
      for:
        hours: 2
```

### Triggers and conditions

The automation editor's own trigger and condition pickers list these. Each takes a device,
area, floor, label or entity target, which names the routines of the devices it covers:

| Kind | In the editor | Key | Fires or holds when |
| --- | --- | --- | --- |
| Trigger | Routine action skipped | `device_routines.action_skipped` | A routine skips a scheduled action or a countdown because it is paused or skipping |
| Trigger | Routine paused | `device_routines.paused` | A routine becomes paused or skipping, and again whenever its pause is replaced or extended |
| Trigger | Routine resumed | `device_routines.resumed` | A pause or skip ends, at its time or by Resume |
| Condition | Routine is paused | `device_routines.is_paused` | The routine is paused or skipping |
| Condition | Routine is active | `device_routines.is_active` | The routine is on and not paused |

Triggers take `behavior` `each` (every routine), `first` (the first of the targeted
routines to change) or `all` (the change that makes it true of every targeted routine).
Conditions take `any` or `all`. `all` counts every targeted routine, including those that
are off, and a target without any routine never fires and never holds. A routine that is
off neither pauses nor resumes.

A notification when a living room routine skips something:

```yaml
triggers:
  - trigger: device_routines.action_skipped
    target:
      area_id: living_room
    options:
      behavior: each
actions:
  - action: notify.notify
    data:
      message: A living room routine skipped an action.
```

A morning automation that runs only while the bedroom's routines are not paused:

```yaml
conditions:
  - condition: device_routines.is_active
    target:
      area_id: bedroom
    options:
      behavior: all
```

### Events

Plain events work as event triggers too. The first is fired by the routine's automation
itself, so it keeps firing with the integration disabled:

| Event | Fired by | Data |
| --- | --- | --- |
| `device_routines_action_skipped` | The routine's automation, when it skips an action | `device_id`, `automation_id`, `trigger_id`, `action`, `scheduled_at` |
| `device_routines_paused` | The integration, when a routine becomes paused or skipping | `device_id`, `automation_id`, `until` |
| `device_routines_resumed` | The integration, when a pause or skip ends | `device_id`, `automation_id`, `until` |

### A card listing every routine

The hub's **Routines** sensor counts the active routines and lists every routine in its
`routines` attribute, each with `device`, `area`, `summary`, `next_action`, `status`
(`active`, `paused`, `skipping`, `off`, `invalid`, `detached` or `missing_target`) and `automation`.
A markdown card over it:

```yaml
type: markdown
title: Routines
content: >-
  {% for routine in state_attr('sensor.device_routines_routines', 'routines') or [] %}
  - **{{ routine.device }}** ({{ routine.area or 'no area' }}): {{ routine.summary }},
    next {{ routine.next_action or 'nothing' }}, {{ routine.status }}
  {% endfor %}
```

Everything the device page can do is also available over Home Assistant's WebSocket API
for custom cards and tools; see [docs/api.md](api.md).

## Console

The **Device Routines** entry in the sidebar opens the console: every routine of the
house on one page. Only administrators see it, because almost everything on it changes
something. It adds no behavior of its own: each button does exactly what the same
control on the device page or the matching action does, and the integration checks it
the same way.

The console has three views, chosen by the tabs at the top (or by the address, such as
`/device-routines/today`):

- **Routines** lists every routine with its device, area, Schedule sentence, status, next
  action and pause. Per row, or for every selected row at once: Skip next, Pause until,
  Resume, Enable and Disable. **Edit settings** opens the routine's times, days, the three
  durations and its switches under the row; Pulse and Only when stay in the automation
  form. A setting that is refused shows why and marks the field. Links open the device
  page and the automation. Below the table:
  - **Opted out devices**: routines whose device was opted out. They are off and keep their
    settings until the cleanup period ends; **Opt in again** keeps the routine.
  - **Detached routines**: routines taken over in the automation editor, now normal
    automations.
  - **Automations that can become routines**: hand written automations that do exactly
    what a routine does. **Convert** shows the automation's sentence and the routine's
    side by side; only **Convert to a routine** changes anything: it creates the routine,
    turns the automation off and labels it `Replaced by routine`. Turning the automation
    back on undoes it.
  - **Add devices**: every device a routine can drive, the ones automations already switch
    at set times marked Suggested, to opt in one at a time or several at once.
- **Today** shows every action planned for one day, the routines' and the hand written
  automations' alike, grouped by area and ordered by time. Actions that conflict are
  highlighted, and an action an Only when condition can hold back says so ("If 1
  condition passes"). Pick another day with the date field. Each row links to its device.
- **Settings** holds every setting of [Settings](#settings), the four maintenance actions
  and Health. A maintenance action always shows first what it would change; **Run now**
  then runs it. Saving settings reloads Device Routines; the console stays open and reads
  the settings again.

Times in the console follow the **Time format** setting, like the sentences; with
Automatic they follow the time format of your own Home Assistant profile.

The console updates by itself while it is open: a routine that changes anywhere (on its
device page, from an automation, from another browser) is read again at once. After
Device Routines is updated, reload the browser page to load the new console.

## Supported devices

The routine drives one entity of the device: the only one in a supported domain without
an entity category, or the one picked in **Routine controls**.

| Domain | Start, label | Stop, label | Options | Built in guard |
| --- | --- | --- | --- | --- |
| `switch`, `light`, `fan`, `input_boolean`, `humidifier` | turn on, "Turn on at" | turn off, "Turn off at" | Times, Days, Turn off after, Turn back on after, Pulse | None |
| `climate` | turn on, "Turn on at" | turn off, "Turn off at" | Times, Days, Turn off after | None |
| `media_player` | none | turn off, "Turn off at" | Turn off at, Days, Turn off after | None |
| `vacuum`, `lawn_mower` | start, "Start at" | return to dock, "Return to dock at" | Times, Days | Starts only when docked (on by default, in the form's Advanced section) |
| `cover` | open, "Open at" | close, "Close at" | Times, Days, Close after | Never opens a garage door, gate or door |
| `lock` | none | lock, "Lock at" | Lock at, Days, Lock after | Never unlocks |
| `valve` | open, "Open at" | close, "Close at" | Times, Days, Close after | Never opens a gas valve |

Some actions are refused because they would weaken safety or security: unlocking a lock,
opening a garage door, gate or door cover, opening a gas valve, and disarming an alarm
(alarm panels and sirens are not supported at all). They are refused when you set a
routine, again when the automation form is edited, and a third time inside the blueprint
itself. Climate is on and off only; there is no temperature scheduling.

## Settings

Settings, Devices and services, Device Routines, Configure, then **Settings**. Defaults apply to routines
created afterwards; changing one never rewrites existing routines.

| Setting | Values | Default |
| --- | --- | --- |
| Schedule sensor scope | All devices with automations, only devices with routines, none | All |
| Time format | Automatic, 12 hour, 24 hour | Automatic (follows the Home Assistant country) |
| Catch up after restart, for new routines | On, off | On |
| Respect manual changes, for new routines | On, off | On |
| Late start window, for new routines | 0 to 180 minutes | 15 |
| Clean up after | 0 (never) to 365 days | 30 |
| Put routines in the device's area | On, off | On |
| On removal | Keep, delete | Keep |
| AI summary entity | An AI Task entity of yours, or none | None |
| AI calls per hour | 1 to 100 | 20 |
| Offer to convert matching automations | On, off (see [Converting automations](#converting-automations)) | On |
| Raise Repairs issues for conflicts | On, off | On |

**AI summary.** Off by default. When you pick one of your own AI Task entities, only the
hand written automations the parser could not fully read are sent to it, one at a time,
as their trigger, condition and action blocks as written, templates included, with
entities named by entity id and devices, areas, floors and labels replaced by numbered
placeholders (no states, no attributes, no names, no aliases or descriptions). The answer, at most twelve words, is cached until the automation changes, marked
`source: ai` and shown with "(AI)". Nothing is sent during the first five minutes after a
start, and never more than the calls per hour you allow.

**Cleanup.** A routine whose device was opted out (the label removed) or removed from
Home Assistant is turned off at once. After the cleanup period its automation and helpers
are deleted; 0 keeps them forever.

The hub's **Clean up now** button runs the cleanup immediately; nothing requires pressing
it.

## Removing the integration

To stop using routines on one device, remove its `Routines` label: the controls go, the
routine is turned off with its settings kept (adding the label back restores them), and
the automation is cleaned up after the cleanup period.

To remove the integration, first choose what happens to the routines with the **On
removal** setting, because Home Assistant's removal dialog cannot ask:

- **Keep** (the default): every routine is taken control of, so it becomes a normal
  automation with the description "Formerly managed by Device Routines." and keeps
  running. The blueprint is removed once nothing uses it. The helpers stay.
- **Delete**: every routine automation and its helpers are deleted.

Then remove Device Routines in Settings, Devices and services. The integration's own
system user, its Repairs issues and its stored data go with it, and so do the `Routines`
label and the `Device Routines` category when nothing carries them any more. If you only want to stop the integration for a while, disable
it instead: routines keep running (see [When the integration is off](#when-the-integration-is-off)).

## Troubleshooting

### Health

The hub's **Health** sensor (a diagnostic entity of the Device Routines device) reads:

| State | Means | What to do |
| --- | --- | --- |
| `ok` | Every check passes. | Nothing. |
| `degraded` | The blueprint file was edited by hand, or a routine's automation does not load. | Look in Repairs: each case has an issue with a fix. |
| `error` | This Home Assistant version lacks something routine editing needs. Routines keep running; editing is off. | Update Device Routines; the state clears by itself. |

Its attributes: `version`; `commit`, `branch` and `deployed_at` (development installs
only); `channel` (`hacs`, `dev` or `unknown`); `ha_version`; `blueprint_schema`;
`blueprint_status` (`ok`, `modified`, or empty before the first check); `owned_count` (the
routines' automations) and `loaded_count` (how many of them loaded); `issues` (the open
Repairs issues of Device Routines); `last_reconcile` (the last self check). The self check
runs at every start and after maintenance, and the attributes follow every change in
between.

### Repairs issues

Device Routines repairs what it can on its own and raises an issue only when a person has
to decide. The hub's **Problem** sensor is on while any of these is open.

Each fixable issue opens one confirmation step that does exactly one thing; a conversion
offer shows both summaries first. If the fix does not take, the step says why and the
issue stays open.

| Issue | When | Fix |
| --- | --- | --- |
| Device Routines cannot read automations on this Home Assistant version | A capability the integration needs is missing on this core. The issue names it and links here. | Nothing to do now: routines keep running and editing is off. Update Device Routines; the issue clears when a compatible version loads. |
| The Device Routines blueprint was changed | The installed blueprint differs from the shipped one and from the last one installed. | Reinstall the shipped blueprint; the automations that use it reload. Your changes to the file are lost. |
| The routine of a device cannot run as edited | The automation form or file was saved with inputs a routine cannot use, or with a refused action. The routine was turned off. | Restore the last valid settings, which turns the routine back on. Correcting the form clears the issue too. |
| The routine of a device is now a normal automation | Someone took control of the routine's automation. | Create a new routine for the device with the settings it had. The old automation is never touched: turn it off or delete it yourself. |
| The weekly schedule of a device is empty | The schedule helper was deleted and created again without blocks. | Open the helper (Settings, Devices and services, Helpers) and enter the blocks; the issue clears by itself once it has blocks. |
| A change to the routine of a device was not saved | Something else changed `automations.yaml` twice while the routine was being saved. | Save the change again. |
| The routine of a device does not load | Its automation did not load even after one regeneration. | Regenerate it from the last valid settings, or read the Home Assistant log for the reason. |
| Two automations drive a device in opposite directions | A routine and another automation act on the same device in opposite directions in the same minute. One issue per routine, only while Raise Repairs issues for conflicts is on. | Change one of them; the issue clears when they no longer collide. |
| An automation can become a routine on a device | A hand written automation that is turned on does exactly what a routine on a device without one would do. One issue per automation, only while Offer to convert matching automations is on. | Convert it: the routine is created, the automation is turned off and labeled Replaced by routine (see [Converting automations](#converting-automations)). Ignore the issue to keep the automation. |

Situations that heal on their own, with no issue: a missing blueprint is reinstalled, a
missing timer helper is created again, a deleted `Routines` label is created again and
put back on every device that had it, a renamed device or entity is followed, a deleted
routine automation resets the routine, and a routine whose device entity disappears is
turned off until it returns.

### Diagnostics

Settings, Devices and services, Device Routines, the three dot menu, Download
diagnostics; the Device Routines hub device offers the same. Attach the file to a bug
report. It holds counts, settings, the adapter report, the Health report and one shape
per routine. Entity ids, device ids, device and area names, aliases and anything that
looks like a token or an address are redacted.

## Limitations

- **Comments in `automations.yaml`.** Every routine write rewrites the file and drops its
  comments and anchors, exactly as the automation editor does.
- **A countdown that ran out during a restart** is acted on only with the integration
  loaded (see [When the integration is off](#when-the-integration-is-off)).
- **Daylight saving nights** follow Home Assistant's time trigger: a skipped time does not
  run that night, a repeated one runs twice (see [Daylight saving nights](#daylight-saving-nights)).
- **Helpers have no device.** The timer and schedule helpers do not appear on the device
  page; Home Assistant no longer keeps a device on a helper that has no integration of its
  own. Find them through the `Routines` label or their entity ids.
- **Minutes, not seconds.** Times are minutes and durations are minutes, up to 1440.
- **One routine per device**, driving one entity of it. Devices with several controllable
  entities pick one in Routine controls.
- **No house wide pause or vacation mode** in this version; pause a room or a label with
  the actions instead.
- **Climate is on and off only**; there is no temperature or media scheduling.
- **Entities without a device** cannot have a routine.
- **Not an automation engine.** Anything beyond the controls above stays a normal
  automation, which the Schedule sensor still summarizes.
- **Summaries never guess.** Templates, scripts, repeats and events in a hand written
  automation read as "custom logic".
