# Device Routines WebSocket API

The console contract of TECH_SPEC 4.7 and PRD 7.5: every capability of a device page is
reachable here with the same semantics (goal G9), so the console of Build B and any
dashboard card can be built without touching the integration. Every command is a thin
caller of the service layer (PRD P16): the RoutineManager, the SummaryCoordinator, the
global settings and the maintenance actions. `tests/integration/test_websocket_api.py`
proves each command against the service layer's own result; the examples below are
payloads those tests produce, with device ids replaced by readable placeholders.

The examples use a synthetic home: a living room fan (`switch.living_room_fan`) with a
routine from 5:00 PM to 11:00 PM, a desk lamp (`light.desk_lamp`) in the same room, a
garage door, a hand written automation that turns the lamp on at 7:00 AM and one that
turns the fan on at 11:00 PM. The clock reads Monday 2026-10-19, 4:00 PM, in Los Angeles.

## Commands

| Command | Admin | Request fields | Result |
| --- | --- | --- | --- |
| [`device_routines/routines/list`](#routineslist) | No | none | `routines`: list of RoutineView |
| [`device_routines/routines/get`](#routinesget) | No | `device_id` | RoutineView |
| [`device_routines/routines/set`](#routinesset) | Yes | `device_id`, `settings` | RoutineView |
| [`device_routines/routines/action`](#routinesaction) | Yes | `action`, `target`, `until`, `for` | `results`, `ignored` |
| [`device_routines/devices/opt`](#devicesopt) | Yes | `op`, `device_id` | `devices`, or `results` |
| [`device_routines/schedule/today`](#scheduletoday) | No | `date` | `date`, `items` |
| [`device_routines/settings/get`](#settingsget) | No | none | GlobalSettings |
| [`device_routines/settings/set`](#settingsset) | Yes | `settings` | GlobalSettings |
| [`device_routines/maintenance`](#maintenance) | Yes | `action`, `dry_run` | MaintenanceReport |
| [`device_routines/subscribe`](#subscribe) | No | none | `null`, then events |

The commands exist once the integration has been set up. They speak Home Assistant's own
WebSocket protocol: authenticate, then send a message with an `id` and a `type`; the
answer is a `result` message with the same `id`. A command marked Admin answers a user
who is not an administrator with the core's `unauthorized` error.

## Conventions

Payloads are flat and mirror the service layer: each result is the service layer's
dataclass serialized with `dataclasses.asdict`.

| Python value | JSON |
| --- | --- |
| `datetime` | ISO 8601 string with its offset, `"2026-10-19T17:00:00-07:00"`. Instants the manager computes are local; a pause given as a duration is stored in UTC (`"+00:00"`) |
| `time` | `"HH:MM:SS"`, `"17:00:00"` |
| enum | its value, `"every_day"`, `"active"`, `"on"` |
| set of weekdays | a list from Monday to Sunday, `["mon", "sat"]` |
| tuple, list | a list |
| missing value | `null` |

### Errors

A refusal of the service layer is an error message whose `code` is its translation key.
The console renders `translation_key` with `translation_placeholders` from the
integration's `exceptions` translations; `message` is the English text, or the key when
translations are not loaded. A problem about one setting names it in the `setting`
placeholder, so a form can mark the field.

```json
{
  "id": 6,
  "type": "result",
  "success": false,
  "error": {
    "code": "same_on_and_off_time",
    "message": "The start and stop times are the same. Choose two different times",
    "translation_key": "same_on_and_off_time",
    "translation_placeholders": {"setting": "off_time"},
    "translation_domain": "device_routines"
  }
}
```

| Code | When |
| --- | --- |
| `invalid_format` | The request does not have the command's shape (the core's error, no translation key) |
| `unauthorized` | A writing command from a user who is not an administrator (the core's error) |
| `not_loaded` | The config entry is not loaded, for example during a reload |
| any other | The translation key of the refusal, listed with each command |

### Reloads

Storing new global settings reloads the config entry, which replaces the manager, exactly
as the options flow does. Commands find the loaded entry at every call, so they keep
working after a reload; during the reload itself they answer `not_loaded`. Subscriptions
follow the new manager by themselves (see [subscribe](#subscribe)).

## Types

### RoutineView

One routine as every surface sees it (TECH_SPEC 4.1).

| Field | Type | Meaning |
| --- | --- | --- |
| `device_id` | string | The device the routine belongs to |
| `device_name` | string | Its name, as the user named it |
| `area_id` | string or null | The device's area |
| `automation_id` | string | The managed automation's id (`device_routines_` plus 12 hex characters) |
| `automation_entity_id` | string or null | Its entity id, null before the first setting is written |
| `settings` | RoutineSettings | Every setting of the routine |
| `status` | string | `active`, `paused`, `skipping`, `off`, `detached`, `missing_target` or `invalid` |
| `enabled` | bool | The Routine switch |
| `paused_until` | datetime or null | While paused or skipping |
| `skipped_action` | Occurrence or null | What Skip next skipped, while skipping |
| `next_action` | Occurrence or null | The next action that really runs, after any pause |
| `sentence` | string or null | The Schedule sensor's state |
| `items` | list of SummaryItem | The Schedule items of the device, routine first |
| `conflicts` | list of Conflict | FR-S6 conflicts among the items |
| `override` | bool | The Manual override |
| `last_change_source` | string or null | `automation`, `user` or `device` |

### RoutineSettings

The fields of `settings` in a RoutineView. `routines/set` takes any subset of them; it
accepts the JSON forms shown, and the native forms the manager stores (`apply_patch`).

| Field | JSON form | Default |
| --- | --- | --- |
| `target_entity` | entity id of one of the device's controllable entities | the first candidate |
| `on_time`, `off_time` | `"HH:MM"` or `"HH:MM:SS"`, or null; counts only with the kind `time` | null |
| `on_kind`, `off_kind` | `time`, `sunrise` or `sunset` (FR-R10); a sun kind sets its side without a time | `time` |
| `on_sun_offset_min`, `off_sun_offset_min` | whole minutes from -180 to 180, negative before the event; counts only with a sun kind | 0 |
| `days` | `every_day`, `weekdays`, `weekends`, `some_days`, `weekly_schedule` | `every_day` |
| `day_set` | list of `mon` to `sun`; counts only with `some_days` | all seven |
| `schedule_entity` | a `schedule` entity id, with `weekly_schedule` | null |
| `turn_off_after_min`, `turn_back_on_after_min` | whole minutes, 0 for off; at most one of them | 0 |
| `catch_up`, `respect_manual`, `docked_guard` | bool | true |
| `late_start_window_min` | whole minutes | 15 |
| `pulse` | `{"at": "08:00", "minutes": 3, "min_steady_min": 5}` or null | null |
| `extra_conditions` | list of condition mappings | `[]` |

### Occurrence

`{"at": datetime, "verb": string or null}`; the verb is `on`, `off`, `toggle`, `start`,
`dock`, `pause`, `stop`, `open`, `close`, `lock` or `unlock`.

### SummaryItem and Conflict

A SummaryItem is one Schedule item: `kind` (`routine`, `automation` or
`detached_routine`), `automation_entity`, `alias`, `summary`, `next_run`, `source`
(`parser`, `ai` or `none`), `enabled`, `custom_logic` and `parts` (the routine's lines).
A Conflict names two item indexes `a` and `b`, a `reason_key` (`opposite_same_minute`,
`off_in_on_window` or `on_in_off_window`) and the moment `at`.

## routines/list

Every routine the manager knows, sorted by device name: devices opted in, and devices
opted out whose routine waits for cleanup.

```json
{"id": 2, "type": "device_routines/routines/list"}
```

```json
{
  "routines": [
    {
      "device_id": "dev_living_room_fan",
      "device_name": "Living room fan",
      "area_id": "living_room",
      "automation_id": "device_routines_5c1e0f3a9b72",
      "automation_entity_id": "automation.routine_living_room_fan",
      "settings": {
        "target_entity": "switch.living_room_fan",
        "on_time": "17:00:00",
        "off_time": "23:00:00",
        "days": "every_day",
        "day_set": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
        "schedule_entity": null,
        "turn_off_after_min": 0,
        "turn_back_on_after_min": 0,
        "catch_up": true,
        "late_start_window_min": 15,
        "respect_manual": true,
        "pulse": null,
        "extra_conditions": [],
        "docked_guard": true,
        "on_kind": "time",
        "on_sun_offset_min": 0,
        "off_kind": "time",
        "off_sun_offset_min": 0
      },
      "status": "active",
      "enabled": true,
      "paused_until": null,
      "skipped_action": null,
      "next_action": {"at": "2026-10-19T17:00:00-07:00", "verb": "on"},
      "sentence": "On at 5:00 PM",
      "items": [
        {
          "kind": "routine",
          "automation_entity": "automation.routine_living_room_fan",
          "alias": "Routine: Living room fan",
          "summary": "5:00 PM: on, 11:00 PM: off",
          "next_run": "2026-10-19T17:00:00-07:00",
          "source": "parser",
          "enabled": true,
          "custom_logic": false,
          "parts": ["5:00 PM: on", "11:00 PM: off"]
        },
        {
          "kind": "automation",
          "automation_entity": "automation.late_fan_on",
          "alias": "Late fan on",
          "summary": "11:00 PM: on",
          "next_run": "2026-10-19T23:00:00-07:00",
          "source": "parser",
          "enabled": true,
          "custom_logic": false,
          "parts": []
        }
      ],
      "conflicts": [
        {"a": 0, "b": 1, "reason_key": "on_in_off_window", "at": "2026-10-19T23:00:00-07:00"},
        {"a": 0, "b": 1, "reason_key": "opposite_same_minute", "at": "2026-10-19T23:00:00-07:00"}
      ],
      "override": false,
      "last_change_source": null
    }
  ]
}
```

## routines/get

One device's routine.

| Field | Type | Required |
| --- | --- | --- |
| `device_id` | string | yes |

```json
{"id": 3, "type": "device_routines/routines/get", "device_id": "dev_living_room_fan"}
```

The result is one RoutineView, as in [routines/list](#routineslist). Errors:
`not_opted_in` (placeholder `device`) for a device without routine controls.

```json
{
  "code": "not_opted_in",
  "message": "Garage door has no routine controls. Add the Routines label to it, or choose it in the Device Routines options",
  "translation_key": "not_opted_in",
  "translation_placeholders": {"device": "Garage door"},
  "translation_domain": "device_routines"
}
```

## routines/set

A partial settings update for one device, validated against the merged settings by the
compiler, shown at once and written about a second later (the manager's debounce).

| Field | Type | Required |
| --- | --- | --- |
| `device_id` | string | yes |
| `settings` | object of RoutineSettings fields | yes |

```json
{
  "id": 5,
  "type": "device_routines/routines/set",
  "device_id": "dev_living_room_fan",
  "settings": {"off_time": "22:30", "days": "weekdays"}
}
```

The result is the RoutineView with the new settings (`"off_time": "22:30:00"`,
`"days": "weekdays"`). On a problem nothing changes and the error names the setting:

| Code | Placeholders | When |
| --- | --- | --- |
| `unknown_setting` | `setting` | A field RoutineSettings does not have |
| `invalid_value` | `setting` | A value of the wrong form |
| `invalid_target` | `setting`, `entity` | A target entity the device does not offer |
| `same_on_and_off_time`, `no_days_selected`, `schedule_entity_missing`, `times_with_weekly_schedule`, `both_durations` | `setting` | The compiler's validation |
| `on_time_not_supported`, `duration_not_supported`, `pulse_not_supported` | `setting`, `domain` | An option the device's domain does not have |
| `refused_action` | `setting`, `action` | A refused action (PRD 5.4) |
| `not_opted_in`, `detached` | `device` | The device has no routine controls, or its routine was taken over |
| `editing_unavailable` | none | The adapter cannot write on this Home Assistant version |

## routines/action

Skip next, pause, resume, enable or disable over a native target, exactly as the
`device_routines` actions do (FR-R11 to FR-R15).

| Field | Type | Required |
| --- | --- | --- |
| `action` | `skip_next`, `pause`, `resume`, `enable` or `disable` | yes |
| `target` | object with any of `device_id`, `entity_id`, `area_id`, `floor_id`, `label_id` (each a string or a list), or `"all"` | yes |
| `until` | datetime; without an offset it is local time | `pause` only, exactly one of `until` and `for` |
| `for` | duration: `"HH:MM:SS"`, seconds, or `{"hours": 1, "minutes": 30}` | `pause` only |

```json
{
  "id": 8,
  "type": "device_routines/routines/action",
  "action": "skip_next",
  "target": {"area_id": "living_room"}
}
```

```json
{
  "results": [
    {
      "device_id": "dev_living_room_fan",
      "device_name": "Living room fan",
      "action": "skip_next",
      "paused_until": "2026-10-19T23:01:00-07:00",
      "skipped_action": {"at": "2026-10-19T17:00:00-07:00", "verb": "on"},
      "next_action": {"at": "2026-10-20T17:00:00-07:00", "verb": "on"}
    }
  ],
  "ignored": [{"target": "dev_desk_lamp", "kind": "device", "reason": "no_routine"}]
}
```

`results` has one entry per routine device the target covers. `ignored` lists every
device, entity, area, floor or label the target names that has no routine, with the
reason (`no_routine`, `detached`, or the translation key of a refusal such as
`nothing_to_skip`), as S13 asks. A pause for a duration:

```json
{
  "id": 9,
  "type": "device_routines/routines/action",
  "action": "pause",
  "target": {"device_id": "dev_living_room_fan"},
  "for": "01:30:00"
}
```

Errors: `pause_until_or_for` (a pause without exactly one of `until` and `for`),
`no_routine_targets` (nothing the target covers has a routine) and `target_all_reserved`:
the schema accepts a target of `"all"` so a house wide action can be added later without
a breaking change (PRD 4.4, D24), and refuses it until then.

## devices/opt

Lists the devices a routine can drive, suggests the ones hand written time based
automations already drive, and opts devices in or out (PRD 4.1).

| Field | Type | Required |
| --- | --- | --- |
| `op` | `list`, `suggest`, `in` or `out` | yes |
| `device_id` | string or list of strings | for `in` and `out` |

`list` and `suggest` return `devices`, each with `device_id`, `name`, `area_id` and
`targets` (the entities a routine could drive):

```json
{"id": 13, "type": "device_routines/devices/opt", "op": "suggest"}
```

```json
{
  "devices": [
    {
      "device_id": "dev_desk_lamp",
      "name": "Desk lamp",
      "area_id": "living_room",
      "targets": ["light.desk_lamp"]
    }
  ]
}
```

`in` and `out` return `results`, one per device in the order given, each with
`device_id`, `opted_in`, `changed` (false when the device already was) and the updated
`view`:

```json
{"id": 14, "type": "device_routines/devices/opt", "op": "in", "device_id": ["dev_desk_lamp"]}
```

```json
{
  "results": [
    {
      "device_id": "dev_desk_lamp",
      "opted_in": true,
      "changed": true,
      "view": {
        "device_id": "dev_desk_lamp",
        "device_name": "Desk lamp",
        "area_id": "living_room",
        "automation_id": "device_routines_9a40d27e18c5",
        "automation_entity_id": null,
        "settings": {"target_entity": "light.desk_lamp", "on_time": null, "off_time": null},
        "status": "off",
        "enabled": false,
        "next_action": null,
        "sentence": "On Tue 7:00 AM"
      }
    }
  ]
}
```

(The view is shortened here; it is a full RoutineView.) Devices are handled one after
another: the first refusal ends the command with its error and the devices before it stay
changed; opting in again is harmless. Errors: `unknown_device` and `not_eligible`
(placeholder `device`).

## schedule/today

Every action planned for one local day on every device, routines and hand written
automations alike, for the console's Today view (PRD 4.5).

| Field | Type | Required |
| --- | --- | --- |
| `date` | `"YYYY-MM-DD"` | no; today by default |

```json
{"id": 16, "type": "device_routines/schedule/today"}
```

```json
{
  "date": "2026-10-19",
  "items": [
    {
      "time": "2026-10-19T07:00:00-07:00",
      "device_id": "dev_desk_lamp",
      "area_id": "living_room",
      "action": "on",
      "kind": "automation",
      "automation": "automation.morning_lamp",
      "conflict": false
    },
    {
      "time": "2026-10-19T17:00:00-07:00",
      "device_id": "dev_living_room_fan",
      "area_id": "living_room",
      "action": "on",
      "kind": "routine",
      "automation": "automation.routine_living_room_fan",
      "conflict": false
    },
    {
      "time": "2026-10-19T23:00:00-07:00",
      "device_id": "dev_living_room_fan",
      "area_id": "living_room",
      "action": "on",
      "kind": "automation",
      "automation": "automation.late_fan_on",
      "conflict": true
    },
    {
      "time": "2026-10-19T23:00:00-07:00",
      "device_id": "dev_living_room_fan",
      "area_id": "living_room",
      "action": "off",
      "kind": "routine",
      "automation": "automation.routine_living_room_fan",
      "conflict": true
    }
  ]
}
```

Items are sorted by time, then device and automation. The day reads the schedule as it
stands now: an action earlier in the day is listed as planned (here the 7:00 AM lamp),
a routine action its pause skips (after now and before Paused until) and every action of
an automation that is turned off are left out. `action` is null when it is not known yet
(a routine whose automation is not loaded). `area_id` is the device's area. `conflict`
marks an action that takes part in an FR-S6 conflict in its own minute: two opposite
actions on the device in one minute, or an automation action against the routine's
window (both apply to the 11:00 PM pair above). An unreadable `date` is `invalid_format`.

## settings/get

The global settings of PRD 10.4, as the entry options hold them.

```json
{"id": 17, "type": "device_routines/settings/get"}
```

```json
{
  "schedule_scope": "all",
  "time_format": "auto",
  "default_catch_up": true,
  "default_respect_manual": true,
  "default_late_start_window_min": 15,
  "cleanup_after_days": 30,
  "assign_area": true,
  "on_removal": "keep",
  "ai_task_entity": null,
  "ai_calls_per_hour": 20,
  "offer_conversions": true,
  "raise_conflict_repairs": true
}
```

## settings/set

A partial change of the global settings, validated like the options flow, stored in the
entry options; the entry then reloads (see [Reloads](#reloads)). The result is the
complete settings after the change. Values equal to the stored ones change nothing and
reload nothing.

| Field | Type | Required |
| --- | --- | --- |
| `settings` | object of GlobalSettings keys | yes |

```json
{"id": 20, "type": "device_routines/settings/set", "settings": {"time_format": "24h"}}
```

The result is the object of [settings/get](#settingsget) with `"time_format": "24h"`.
Errors, each with the `setting` placeholder:

| Code | More placeholders | When |
| --- | --- | --- |
| `unknown_setting` | none | A key the catalog does not have |
| `invalid_choice` | `allowed` | `schedule_scope`, `time_format` or `on_removal` outside its values |
| `invalid_boolean` | none | A switch setting that is not true or false |
| `out_of_range` | `min`, `max` | `default_late_start_window_min` (0 to 180), `cleanup_after_days` (0 to 365), `ai_calls_per_hour` (1 to 100) |
| `invalid_ai_task_entity` | none | `ai_task_entity` that is not an `ai_task` entity id or null |

```json
{
  "code": "invalid_choice",
  "message": "time_format must be one of: auto, 12h, 24h",
  "translation_key": "invalid_choice",
  "translation_placeholders": {"setting": "time_format", "allowed": "auto, 12h, 24h"},
  "translation_domain": "device_routines"
}
```

## maintenance

One of the maintenance actions of PRD 10.4, idempotent and safe at any time.

| Field | Type | Required |
| --- | --- | --- |
| `action` | `clean_up_now`, `rebuild_index`, `reinstall_blueprint` or `refresh_summaries` | yes |
| `dry_run` | bool | no; false by default |

```json
{"id": 19, "type": "device_routines/maintenance", "action": "clean_up_now", "dry_run": true}
```

```json
{"action": "clean_up_now", "changed": [], "would_change": ["dev_desk_lamp"]}
```

With `dry_run` nothing changes and `would_change` lists what would; without it `changed`
lists what changed. The entries are device ids (`clean_up_now`, `refresh_summaries`),
automation ids (`rebuild_index`) or the blueprint path (`reinstall_blueprint`).

## subscribe

Pushes what the console needs to refresh. The result is `null`; events follow with the
subscription's `id` until the client sends `unsubscribe_events` with that id or closes
the connection.

```json
{"id": 1, "type": "device_routines/subscribe"}
```

```json
{
  "id": 1,
  "type": "event",
  "event": {"kind": "routine_changed", "device_id": "dev_desk_lamp", "reason": "opted_in", "data": null}
}
```

| `kind` | `device_id` | When |
| --- | --- | --- |
| `routine_changed` | the device | Any change of a routine: settings, status, pause, skip, override, opt in or out. `reason` is `opted_in`, `opted_out` or `device_routines_action_skipped` when known; with the last, `data` carries the blueprint event's data |
| `schedule_changed` | null | The manager reconciled or refreshed every summary: re read the Today view |
| `settings_changed` | null | The entry was set up again with other global settings |
| `health_changed` | null | Health inputs changed (reconcile, blueprint reinstall) |

```json
{
  "id": 1,
  "type": "event",
  "event": {
    "kind": "routine_changed",
    "device_id": "dev_living_room_fan",
    "reason": "device_routines_action_skipped",
    "data": {"device_id": "dev_living_room_fan", "action": "on", "at": "2026-10-19T17:00:00-07:00"}
  }
}
```

Known limit: an edit of a hand written automation changes the summary but pushes no
event yet, because the summary has no house wide change signal; the Today view re reads
on `schedule_changed` and whenever it opens.

Across reloads. A subscription listens to the manager of the entry that is set up, and
every setup tells it to listen to the new manager before that manager starts, so the
events of its first reconcile arrive too. When the new entry runs with other global
settings, the first event after the reload is `settings_changed`. A subscription made
while no entry is set up succeeds and starts hearing events at the next setup.
