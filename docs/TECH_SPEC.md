# Device Routines technical specification

Oct 13, 2026 · @Jayant Yadav

Companion to the PRD tab PRD (public) (what the integration does) and the Implementation plan tab (in what order, with what validation). This tab is public and becomes `docs/TECH_SPEC.md`. It contains no instance data.

## 1. Scope and precedence

- The PRD defines behavior. This spec defines how that behavior is built: module boundaries, data shapes, the blueprint, storage, the deployment pipeline and the test matrix, at the depth a reviewer needs to judge a pull request.
- Precedence: the PRD over this spec for behavior; this spec over the Implementation plan for design; the plan over both for order and validation.
- PRD assumptions stay open until Stage 0 closes them. Where a fallback exists it is written next to the capability here, so a failed probe changes a paragraph, not the design.
- Style rules apply to code, comments, docs and commit messages: no em dash character anywhere; a translation key for every user facing string; conventional commits.

## 2. System overview

| Path | Needs the integration | Components |
| --- | --- | --- |
| Configure | Yes | Device page entity, RoutineManager, compiler, ha\_adapter, `automations.yaml`, one automation reload |
| Sync back | Yes | `automation_reloaded` event, RoutineManager, decompile, entities |
| Run | No | Blueprint automation, timer helper, schedule helper, Manual override switch, Paused until entity |
| Read | Yes | SummaryCoordinator, discovery, parser, nextrun, conflicts, Schedule sensors, hub sensors, WebSocket API |
| Attribute | Yes, degrades to off | `attribution.py` feeds the Manual override switch that the blueprint reads |

Service layer rule (PRD P16). Behavior exists only in `manager.py` (RoutineManager), `summary.py` (SummaryCoordinator), `attribution.py`, `settings.py` and `maintenance.py`. Every platform entity, action handler, trigger, condition, Repairs fix flow and WebSocket command is a thin caller. A reviewer rejects any pull request where a platform file contains a rule.

Import rules, enforced by a test that parses the AST of every module:

| Module group | May import |
| --- | --- |
| Pure: `models`, `domains`, `compiler`, `markers`, `parser`, `parser_grammar`, `nextrun`, `conflicts`, `sentence`, `settings` | Standard library and each other |
| `ha_adapter` | `homeassistant.*`, including internals of `automation`, `blueprint`, `timer`, `schedule` and `config` |
| Everything else | `homeassistant.core`, `homeassistant.helpers.*`, the base classes of its own platform, the pure modules, `ha_adapter` |

## 3. Pure modules

All pure modules are deterministic, side effect free and typed for `mypy --strict`. They take plain dataclasses and return plain dataclasses, or raise `CompileError` or `ParseError` carrying a translation key and placeholders.

### 3.1 models.py

```python
class Days(StrEnum):     EVERY_DAY, WEEKDAYS, WEEKENDS, SOME_DAYS, WEEKLY_SCHEDULE
class Weekday(StrEnum):  MON, TUE, WED, THU, FRI, SAT, SUN
class Status(StrEnum):   ACTIVE, PAUSED, SKIPPING, OFF, DETACHED, MISSING_TARGET, INVALID
class Source(StrEnum):   AUTOMATION, USER, DEVICE

@dataclass(frozen=True)
class RoutineSettings:
    target_entity: str
    on_time: time | None = None
    off_time: time | None = None
    days: Days = Days.EVERY_DAY
    day_set: frozenset[Weekday] = ALL_DAYS      # effective for SOME_DAYS, derived otherwise
    schedule_entity: str | None = None          # WEEKLY_SCHEDULE only
    turn_off_after_min: int = 0
    turn_back_on_after_min: int = 0
    catch_up: bool = True
    late_start_window_min: int = 15
    respect_manual: bool = True
    pulse: Pulse | None = None
    extra_conditions: tuple[Mapping[str, Any], ...] = ()
    docked_guard: bool = True                   # vacuum and lawn_mower only

@dataclass(frozen=True)
class DomainProfile:
    domain: str
    on_action: str | None
    off_action: str
    inactive_state: str
    on_label_key: str | None
    off_label_key: str
    options: frozenset[Option]
    refused_device_classes: frozenset[str]

@dataclass(frozen=True)
class CompiledInputs:    inputs: Mapping[str, Any]   # the exact blueprint input dict, keys in a fixed order
@dataclass(frozen=True)
class SummaryItem:       kind, automation_entity, alias, summary, next_run, source, enabled, custom_logic, parts
@dataclass(frozen=True)
class Conflict:          a: int, b: int, reason_key: str, at: datetime | None
```

### 3.2 domains.py

`PROFILES` holds one `DomainProfile` for `switch`, `light`, `fan`, `input_boolean`, `humidifier`, `climate`, `media_player`, `vacuum`, `lawn_mower`, `cover`, `lock` and `valve`. `profile_for(domain, device_class)` applies the PRD 5.3 refusals (cover garage, gate and door classes get no open action; valve gas gets no open action; lock and media player have no on action). `pick_targets(entities)` returns the controllable candidates: supported domain, no entity category, registry order. `inactive_state` is `off` for switch, light, fan, input\_boolean, humidifier, climate and media\_player, `docked` for vacuum and lawn\_mower, `closed` for cover and valve, `locked` for lock. The blueprint fires `device_on` on `from: inactive_state` and `device_off` on `to: inactive_state`, so every domain shares the same two triggers, including climate with its many modes.

### 3.3 compiler.py

- `validate(settings, profile) -> list[Problem]`. Rejects: a refused action; `on_time == off_time`; a duration on a domain without that option; both `turn_off_after_min` and `turn_back_on_after_min` non zero (D27); `WEEKLY_SCHEDULE` without `schedule_entity`; `SOME_DAYS` with an empty `day_set`; `pulse` on a domain without both actions; an on time on a domain without an on action.
- `compile(settings, profile, refs) -> CompiledInputs`. Produces the full blueprint input dict of Section 5.2 including the derived inputs: `days_start`, `days_end` (the day set shifted by one when the window crosses midnight, else identical), `crosses_midnight`, `late_window_end` (on time plus the late start window, wrapped at midnight), `on_time_enabled`, `off_time_enabled`, sentinel values for every disabled input, `on_action`, `off_action`, `inactive_state`, helper entity ids and the device id carried in events.
- `decompile(inputs) -> RoutineSettings`. The inverse. Property tests: `decompile(compile(s)) == s` for every valid `s`, and `compile(decompile(i)) == i` for every `i` produced by `compile`.
- `is_valid_shape(inputs) -> bool`, used by sync back: an unknown key, a missing required key or a type mismatch means the automation was edited into an invalid state.

### 3.4 markers.py

- `automation_id(device_id)`: `device_routines_` plus the first 12 hex characters of sha256(device\_id). Stable across renames.
- `is_owned(config)`: M1 regex `^device_routines_[0-9a-f]{12}$` and M2 `use_blueprint.path == device_routines/device_routine.yaml`. Both required.
- `presentation(device_name, lang)`: alias `Routine: <device name>`, the M4 description, icon, category and label names.
- `alias_is_generated(alias, names)`: true while the alias matches the pattern for the current device name or any previous name recorded in the Store, so renames follow and a human edit sticks.
- `config_hash(config)`: sha256 of canonical JSON (sorted keys, no whitespace) of the entry without `id`.

### 3.5 parser.py and parser\_grammar.py

`summarize(config, device, lang) -> list[SummaryItem]`, one item per action on the device. The grammar is data: tables of trigger kinds, condition kinds and action verbs per domain, each with a test. Any construct outside the grammar in a branch marks the item `custom_logic`; an item with no understood part becomes the single translated line `automation_custom` (Automation: alias, custom logic). No heuristics, no defaults, no guessing: every line is produced by a rule with a test, which is how G5 (zero wrong lines) is kept.

### 3.6 nextrun.py

- `next_occurrences(item, now, tz, sun) -> list[Occurrence]` and `next_run(...)`.
- `expected_state(settings, now, schedule_state) -> on | off | None`, the single source of truth for catch up, skip targets and sentences. A window belongs to the weekday it starts on: a window from 17:00 to 09:00 with Weekdays is off on Monday at 08:00 because Sunday is not a start day.
- `skip_target(settings, now, paused_until, schedule_state) -> SkipTarget`: the action the sentence shows, with its paired end for a window start (D18) and the resulting Paused until value.
- DST: times are wall clock and the rules mirror the HA time trigger as Stage 0 observed it (A7, V10, decision L21): a time that does not exist on the spring forward day does not run that day at all; a time that exists twice on the fall back day runs twice, once per offset, an hour apart. The device state guard makes the second on or off a no op. Tested on the 2026 US and EU dates.

### 3.7 conflicts.py

`find(items, window) -> list[Conflict]`: opposite actions on the same entity in the same minute, and an automation action that contradicts a routine window (an off inside an on window, an on inside an off window). Pure, O(n log n).

### 3.8 sentence.py

`state_sentence(view, now, fmt, lang) -> str` and `item_line(item, fmt, lang) -> str` build every user visible sentence from translation tables (`translations/<lang>.json`, `sentence` section). Hard cap of 40 characters for the state: the formatter drops, in order, the weekday, then the action adjective, then falls back to Next: time. A test generates every combination and asserts the cap. Time format: `12h` gives 9:00 AM, `24h` gives 09:00; `auto` resolves once at startup from the Home Assistant country (a short list in `const.py` uses 12 hour: US, CA, AU, NZ, IN, PH, EG, SA and a few others).

### 3.9 settings.py

`GlobalSettings` dataclass with the PRD 10.4 keys plus `on_removal` (keep or delete, default keep); `from_options(options, version)` migrates older option sets; `to_options()`; `validate()` returns translated problems.

## 4. Integration modules

### 4.1 RoutineManager (manager.py)

One instance per config entry in `entry.runtime_data`. Every method is async and returns a result dataclass; the only exception raised to callers is `ServiceValidationError` with a translation key.

| Method | Does |
| --- | --- |
| `async_opt_in(device_id, source)` and `async_opt_out(device_id, source)` | Applies or removes the label, creates or removes the entities, turns the routine off on opt out, records `opted_out_at` |
| `eligible_devices()` and `suggested_devices()` | Devices with a controllable entity; devices the SummaryCoordinator found with time based automations |
| `get(device_id)` and `list()` | `RoutineView` snapshots |
| `async_update(device_id, patch, source)` | Validates the merged settings, shows the value on the entity at once, debounces one second per device, compiles, writes through the adapter, records the hash, refreshes summaries. On a problem it reverts the entities and returns the translated problem |
| `async_skip_next`, `async_pause(until or for)`, `async_resume`, `async_enable`, `async_disable` | Write Paused until or the automation state; apply D18 to D21; fire the integration triggers |
| `resolve_targets(target)` | Device, area, label and entity targets to routine devices, plus the ignored list used by actions and WebSocket commands |
| `async_sync_back(automation_id, config)` | On `automation_reloaded`: skips hashes it wrote itself; decompiles; validates; updates entities, or turns the routine off and raises `invalid_inputs` |
| `async_handle_removed(automation_id)` and `async_handle_detached(automation_id)` | The PRD 8.2 rows |
| `async_reconcile()` | The Section 7 checklist; at setup and from maintenance |
| `async_cleanup(dry_run)` | D28 |
| `async_add_listener(callback)` | For WebSocket subscriptions and the hub sensors |

`RoutineView` fields: `device_id`, `device_name`, `area_id`, `automation_id`, `automation_entity_id`, `settings`, `status`, `enabled`, `paused_until`, `skipped_action`, `next_action`, `sentence`, `items`, `conflicts`, `override`, `last_change_source`.

Write algorithm (PRD 7.2 in detail): a per device `asyncio.Lock`; read the current entry through the adapter; compare its hash with `owned[id].last_hash`; if it differs and the entry no longer carries M1 and M2, stop with `detached`; compile; write; reload that id only; store `last_hash` and `last_valid_inputs`. If the file changed between the read and the write, retry once, then raise the `write_conflict` Repairs issue.

### 4.2 ha\_adapter.py

The only module allowed to touch internals. Each capability is one small function with a version guard and a fallback. `check(hass) -> AdapterReport` runs at setup: a failed capability disables editing (the config entities become unavailable with a translated reason) and raises the single Repairs issue `adapter_incompatible`, while routines keep running.

| Capability | Primary path | Fallback |
| --- | --- | --- |
| Read automation configs and references | `automations_with_entity`, `automations_with_device`, `automations_with_area`, `automations_with_label` from the automation component, and the entity's `raw_config` (Stage 0 V2: the same config the `automation/config` WebSocket command returns, for UI and YAML automations alike). Device triggers, conditions and actions name entities by registry id, so every entity reference is resolved with `entity_registry.async_resolve_entity_id` before use and an unresolved one is dropped; the core's own `search/related` fails on such automations because it splits the raw id. Helper results include entities that are only read (triggers, conditions), so the summary still keeps action targets only, and entities named only inside templates are invisible to the helpers. The helpers never expand an id (Stage 0, A3 harness), so discovery for a device also asks `automations_with_area` for the device's area and each entity's own area, `automations_with_floor` for those areas' floors and `automations_with_label` for the device's and the entities' labels, and then keeps only actions whose domain matches one of the device's entities. An automation entity without a config (a restored, unavailable registry entry, or a YAML automation ignored for a duplicate id) is skipped | None needed; these are public helpers |
| Write an automation entry | Replicate the config editor: load `automations.yaml`, replace or append the one entry, `write_utf8_file_atomic`, then `automation.reload` with `id`; a delete also removes the entity registry entry, as the editor's delete hook does, or a restored `unavailable` entity stays behind. The editor's lock is an attribute of its HTTP view and not reachable (Stage 0 V6), so the adapter holds its own lock and compares the file hash before the write, with one retry. Reloading one id leaves every other automation's runs alone; it stops the rewritten automation's own run | D2(b): the WebSocket automation config command over loopback with a token the user creates in options |
| Install the blueprint | `homeassistant.components.automation.helpers.async_get_blueprints(hass).async_add_blueprint(Blueprint(yaml, expected_domain=automation, schema=AUTOMATION_BLUEPRINT_SCHEMA), path, allow_override=True)`, the method the `blueprint/save` command calls; usable at once (Stage 0 V5) | Write the file and call `automation.reload` |
| Create timer and schedule helpers | The storage collections are not reachable from code (Stage 0 V7). The adapter dispatches `timer/create`, `timer/update`, `timer/delete` and the `schedule/` equivalents in process through an `ActiveConnection` whose user is the integration's system administrator user (created once, id in the entry data), then `entity_registry.async_update_entity` for the entity id, the label and the device (decision L23) | D2(b): the same commands over loopback with a token, only if the in process dispatch ever breaks |
| Labels and categories | The label and category registry helpers | None |
| Attach entities to devices from other integrations | `DeviceInfo` with the identifiers and the name copied verbatim from the user's device registry entry. On core 2026.10 this creates a record of this config entry carrying those identifiers, which the core lists as a linked device of the user's device (Stage 0 V9, decision L25); the manager removes it when the user's device goes. The device page placement is confirmed live by cleanup item C4 | Decided with the owner if C4 fails (a child device is the candidate) |
| Catch up a timer that ran out during a restart | `restore_state.async_get(hass).last_states` at setup: a routine timer that was `active` with a `finishes_at` in the past was finished during startup before any trigger was armed (Stage 0 V10, decision L20). After the Home Assistant started event the manager fires `device_routines_timer_caught_up` with the device id | None; without the integration the finish is missed, as the user guide states |
| Detect take control | `use_blueprint` absent on an automation whose id carries M1 | None |

### 4.3 attribution.py

- Subscribes to `automation_triggered` and `script_started`; keeps `context.id` to source entity id in an ordered dict capped at 10,000 entries with a 24 hour TTL.
- Subscribes to `state_changed` for routine target entities only. Classification: `AUTOMATION` when `context.id` or `context.parent_id` is in the map; `USER` when the context carries a user id (app, dashboard, voice assistant); otherwise `DEVICE` (wall switch, physical button, the device's own timer). `USER` and `DEVICE` are manual.
- On a manual change, if the routine is active, not paused and `respect_manual` is on: compare the new state with `nextrun.expected_state`; turn the override switch on when they differ and off when a manual change restores the expected state. Records `last_change_source` on the switch.
- Never acts on the device. During the first 30 seconds after Home Assistant start it only fills the map.
- Validation: the V3 recordings (`automation_triggered`, `script_started` and `state_changed` events with contexts, from each protocol, by hand, by app, by voice and from a time triggered automation) replay through the classifier in a unit test.

### 4.4 summary.py (SummaryCoordinator)

- Discovery per PRD FR-S1 into a registry of device id to summary items.
- Recompute triggers: `automation_reloaded`, entity, device and label registry updates, the automation component loaded event, each item's next run (one point in time listener per device, replaced on every recompute) and manager events. Debounce two seconds with a per device coalescing queue. No interval or `time_pattern` listener exists anywhere; a test asserts it.
- Creates and removes Schedule sensors per `schedule_scope` through the sensor platform's add entities callback and removes stale registry entries.
- AI path (Phase 3): a queue with a token bucket (`ai_calls_per_hour`), never during the first five minutes after start, a cache keyed by config hash in the Store, the prompt in `ai_prompt.py`, responses trimmed to twelve words and marked `source: ai`.

### 4.5 Platforms and entities

Base class `DeviceRoutinesEntity` with `has_entity_name`, `unique_id` of the form `device_routines_<device id>_<key>`, `device_info` attaching to the device, `translation_key` equal to the key and icons from `icons.json`. Availability: unavailable with a `reason` attribute when the adapter is incompatible, the routine is detached or the target entity is missing. Entities are removed from the registry on opt out so device pages stay clean.

| Key | Platform | Category | Enabled by default | Calls |
| --- | --- | --- | --- | --- |
| `schedule` | sensor | none | yes | read only |
| `routine` | switch | config | yes | enable, disable |
| `on_time`, `off_time` | time | config | yes | update |
| `days` | select | config | yes | update |
| `turn_off_after` | number, box, 0 to 1440 | config | where the domain supports it | update |
| `turn_back_on_after` | number | config | no | update |
| `catch_up`, `respect_manual` | switch | config | no | update |
| `skip_next`, `resume` | button | none | yes | skip\_next, resume |
| `paused_until` | datetime | none | yes | pause |
| `manual_override` | switch | diagnostic | yes | attribution; a person can turn it off |
| `target` | select | config | only with several candidates | update |

Hub: `hub_routines` (sensor), `hub_problem` (binary\_sensor), `hub_health` (sensor, diagnostic), `hub_cleanup_now` (button, config).

### 4.6 Actions (services.yaml)

`skip_next`, `pause`, `resume`, `enable` and `disable` take a native `target` (entity, device, area, label) filtered to this integration; `pause` adds `until` (datetime selector) or `for` (duration selector), exactly one. `maintenance` takes `action` from clean\_up\_now, rebuild\_index, reinstall\_blueprint and refresh\_summaries. Responses are optional and list `results` (device id, device name, action, paused until, skipped action, next action) and `ignored` (device id, reason). No matching target raises `ServiceValidationError` with the key `no_routine_targets`.

### 4.7 websocket\_api.py (console contract)

Registered in `async_setup_entry`; every writing command requires admin. Payloads are flat and mirror the manager:

| Command | Request fields | Response |
| --- | --- | --- |
| `device_routines/routines/list` | none | `routines`: list of RoutineView |
| `device_routines/routines/get` | `device_id` | RoutineView |
| `device_routines/routines/set` | `device_id`, `settings` (partial) | RoutineView, or `error` with translation key and placeholders |
| `device_routines/routines/action` | `action` (skip\_next, pause, resume, enable, disable), `target` (native target; `all` reserved for a later version), `until`, `for` | `results`, `ignored` as the actions |
| `device_routines/devices/opt` | `op` (list, suggest, in, out), `device_id` list | eligible or suggested devices, or the updated views |
| `device_routines/schedule/today` | `date` | `items`: time, device id, area id, action, kind, automation, conflict flag |
| `device_routines/settings/get` and `set` | `settings` (partial) for set | GlobalSettings |
| `device_routines/maintenance` | `action`, `dry_run` | a report of what was or would be changed |
| `device_routines/subscribe` | none | pushes `routine_changed` (device id), `schedule_changed`, `settings_changed`, `health_changed` |

RoutineView serializes with `dataclasses.asdict`, datetimes as ISO strings. Contract tests call every command through the test WebSocket client and compare with the manager's own results.

### 4.8 Repairs catalog (repairs.py)

Rule: self heal first, raise only when a human decision is genuinely required, and make every issue fixable or link it to the exact place to act. Issue ids are stable and listed by the hub Problem sensor.

| Issue id | Raised when | Fix flow |
| --- | --- | --- |
| `adapter_incompatible` | `check` fails | Not fixable; names the capability and the core version; clears when a compatible build loads |
| `blueprint_modified` | The installed file hash differs from the shipped one and from the last one we installed | One step: reinstall the shipped file and reload automations |
| `invalid_inputs` | Sync back found an invalid shape or a refused action | One step: restore `last_valid_inputs` |
| `detached_routine` | An owned automation lost `use_blueprint` | One step: create a new routine; the detached automation is never touched |
| `schedule_blocks_needed` | A weekly schedule helper was recreated empty | Not fixable; links to the helper |
| `write_conflict` | Two consecutive writes lost a race | One step: retry |
| `automation_load_failed` | An owned automation did not load after one regeneration | One step: regenerate from `last_valid_inputs` |
| `conflict` (Phase 3, behind a setting) | A routine and another automation drive the entity in opposite directions in the same minute | Not fixable; names both |
| `conversion_offer` (Phase 4, behind a setting) | FR-M1 exact match | Two steps: show both summaries, confirm |

### 4.9 diagnostics.py

Config entry and device diagnostics. Redacts entity ids, device ids, device and area names, aliases and anything matching the privacy patterns with `async_redact_data`; keeps domains, shapes, settings, hashes, Store counts and the adapter report.

### 4.10 health.py

Reads `.deployed` next to the component (when present) and `manifest.json`; computes `channel` (`dev` when `.deployed` exists, `hacs` when the HACS store lists the domain, else `unknown`); runs the startup self checks (blueprint installed and its hash status, owned automations loaded, adapter report) and publishes the Health state and attributes of Section 10.3.

### 4.11 migration.py

- Config entry `VERSION 1`, `MINOR_VERSION 1`; `async_migrate_entry` migrates options through `settings.from_options`.
- Store `STORAGE_VERSION 1` with a migrate function.
- Blueprint input schema `BLUEPRINT_SCHEMA_VERSION` in `const.py` and in the blueprint header. At startup, when the shipped schema is newer than `store.blueprint_schema`: install the new blueprint, then for every owned automation decompile with the old rules, compile with the new, write, reload; keep the previous inputs in `owned[id].previous_inputs`; record the new schema. One failure does not stop the others; failed ones get `automation_load_failed`.

### 4.12 config\_flow.py

- `user` step: single instance, no fields; creates the entry, then shows the optional `suggestions` step listing the devices the SummaryCoordinator flagged (all unchecked, with Skip); a selection opts them in.
- Options flow: `settings` (every Section 3.9 key with selectors and descriptions), `devices` (device picker filtered to eligible devices, prefilled with the opted in set), `suggestions` (the same screen as setup, repeatable).
- `async_remove_entry` applies `on_removal`: keep runs take control on every owned automation with the description Formerly managed by Device Routines and removes the blueprint when nothing uses it; delete removes owned automations and their helpers.

## 5. Blueprint specification

### 5.1 File

`custom_components/device_routines/blueprints/device_routine.yaml`, installed to `<config>/blueprints/automation/device_routines/device_routine.yaml`. Header comment: Device Routines blueprint, schema 1; do not edit, changes are detected and offered for restore. `blueprint.name` is Device routine (managed by Device Routines); the description explains that the form is the second editor; `homeassistant.min_version` is the Stage 0 validated version, 2026.10.2. No `source_url`: the file is installed and upgraded by the integration, and a `source_url` would offer a re-import from GitHub in the core and, with Spook, an update entity (decision L24). Every trigger, condition and branch carries an `alias` so a trace reads like documentation.

### 5.2 Inputs

Sections are collapsible; Timers, Behavior and Advanced start collapsed.

| Section | Input | Selector | Default | Notes |
| --- | --- | --- | --- | --- |
| Target | `target_entity` | entity, supported domains | required |  |
| Target | `on_action`, `off_action` | text | required | Service names from the domain profile, for example `switch.turn_on` |
| Target | `inactive_state` | text | required | `off`, `docked`, `closed` or `locked` |
| Target | `device_id` | text | required | Carried in events |
| Schedule | `on_time_enabled`, `on_time` | boolean, time | false, 00:00:00 | Sentinel pattern: a disabled trigger still needs a valid value |
| Schedule | `off_time_enabled`, `off_time` | boolean, time | false, 00:00:00 |  |
| Schedule | `days_start`, `days_end` | select, multiple, weekdays | all days | `days_end` is `days_start` shifted by one day when the window crosses midnight |
| Schedule | `crosses_midnight` | boolean | false |  |
| Schedule | `schedule_enabled`, `schedule_entity` | boolean, entity (schedule) | false, `schedule.device_routines_unused` |  |
| Timers | `timer_entity` | entity (timer) | `timer.device_routines_unused` |  |
| Timers | `turn_off_after_min`, `turn_back_on_after_min` | number 0 to 1440 | 0, 0 | At most one is non zero (D27) |
| Behavior | `catch_up` | boolean | true |  |
| Behavior | `late_start_window_min`, `late_window_end` | number, time | 15, 00:15:00 | `late_window_end` is computed by the compiler |
| Behavior | `respect_manual`, `override_entity` | boolean, entity (switch) | true, `switch.device_routines_unused` |  |
| Behavior | `paused_until_entity` | entity (datetime) | `datetime.device_routines_unused` |  |
| Advanced | `pulse_enabled`, `pulse_at`, `pulse_minutes`, `pulse_min_steady_min` | boolean, time, number, number | false, 00:00:00, 3, 5 |  |
| Advanced | `docked_guard` | boolean | true | vacuum and lawn mower only |
| Advanced | `extra_conditions` | condition | empty | FR-R9 |

Sentinel entities never exist: a state trigger on a missing entity never fires, and `enabled: false` keeps the time triggers inert while their values stay valid for schema validation. V5 confirms `enabled: !input` on triggers and on conditions.

### 5.3 Triggers

| Id | Trigger |
| --- | --- |
| `scheduled_on` | time at `on_time`, enabled `on_time_enabled` |
| `scheduled_off` | time at `off_time`, enabled `off_time_enabled` |
| `block_on`, `block_off` | state of `schedule_entity` to on, to off; enabled `schedule_enabled`. Never `schedule.block_started`, which fires again at midnight between back to back blocks (Stage 0 V10, A6) |
| `ha_start` | Home Assistant start |
| `reconnect` | state of `target_entity` from unavailable, for 10 seconds (a debounce, not a duration that must survive restarts) |
| `device_on` | state of `target_entity` from `inactive_state` |
| `device_off` | state of `target_entity` to `inactive_state` |
| `timer_done` | the purpose specific `timer.finished` trigger on `timer_entity`, and a second trigger with the same id on the event `device_routines_timer_caught_up` filtered on `device_id` (decision L20) |
| `pause_changed` | state of `paused_until_entity` |
| `pause_ended` | omitted: the time trigger refuses a `datetime` entity (Stage 0 V12, decision L22); the integration calls resume at the stored time |
| `override_cleared` | state of `override_entity` to off |
| `pulse` | time at `pulse_at`, enabled `pulse_enabled` |

### 5.4 Shared conditions (repeated per branch; no templates except `not_paused`)

- `not_paused`: one template, `{% set s = states(entity) %}{{ s in ('unknown', 'unavailable', '') or as_datetime(s) <= now() }}`, unit tested. A native time condition is not possible: it refuses a `datetime` entity and compares a timestamp sensor by time of day only (Stage 0 V12, decision L22).
- `expected_on`: with `schedule_enabled`, the schedule entity is on. With `crosses_midnight`, either (time after `on_time` and weekday in `days_start`) or (time before `off_time` and weekday in `days_end`). Otherwise time after `on_time` before `off_time` with weekday in `days_start`. Meaningful only when `has_window` (both times enabled, or a schedule linked).
- `no_override`: the override entity is unavailable or off.
- `device_inactive` and `device_active`: the target state equals, or does not equal, `inactive_state`.
- `extra_ok`: `extra_conditions`, plus the docked guard on every on action for vacuum and lawn mower.

### 5.5 Branches (one choose, mode queued, max 10)

| Trigger ids | Conditions | Actions |
| --- | --- | --- |
| `scheduled_on`, `block_on` | weekday in `days_start` (time triggers only), `not_paused`, `extra_ok` | override off; on action; when `turn_off_after_min` is set and `off_time_enabled` is false: start the timer for that duration |
| `scheduled_off`, `block_off` | weekday in `days_end` (time triggers only), `not_paused` | override off; off action; cancel the timer |
| `device_on` | `not_paused`, `turn_off_after_min` set, not (`has_window` and `expected_on`) | start the timer for `turn_off_after_min` |
| `device_on` | `turn_back_on_after_min` set | cancel the timer |
| `device_off` | `not_paused`, `turn_back_on_after_min` set, `expected_on` or not `has_window` | start the timer for `turn_back_on_after_min` |
| `device_off` | `turn_off_after_min` set | cancel the timer |
| `timer_done` | `not_paused` | with `turn_off_after_min` set: off action; with `turn_back_on_after_min` set: `extra_ok`, then on action |
| `ha_start`, `reconnect`, `override_cleared` | `catch_up`, `not_paused`, `no_override` | with `has_window`: on action when `expected_on` and `device_inactive`, off action when not `expected_on` and `device_active`; one shot (on enabled, off disabled): on action when time after `on_time` before `late_window_end`, weekday in `days_start` and `device_inactive` |
| `pause_changed` | the paused entity is in the future | pause the timer |
| `pause_changed` (a resume, or the integration clearing the entity at the stored end) | the paused entity is not in the future | resume the timer, then the catch up branch (D20) |
| `pulse` | `not_paused`, the device steady for `pulse_min_steady_min` in either state | opposite action; delay `pulse_minutes`; restore. Pulse uses delay deliberately: a restart mid pulse is repaired by catch up, and the timer stays unambiguous for the one duration feature a routine can have |
| any scheduled or countdown branch | `not_paused` false | fire `device_routines_action_skipped` with device id, automation id, trigger id, action and scheduled time, then stop |

Every on and off action is guarded by the device state, so catch up can run twice without side effects.

### 5.6 Upgrades

The blueprint file is replaced whenever the integration ships a new one and automations re read it on reload, so every routine upgrades at once. Input schema changes follow Section 4.11. A hand edited file is never overwritten without the Repairs confirmation.

## 6. Storage and migration

Store `.storage/device_routines`, version 1, keys: `owned` (automation id to device id, target entity, last hash, last valid inputs, previous inputs, schema, alias history), `opted_in` (device ids), `opted_out_at` and `removed_devices_at` (device id to timestamp), `blueprint_hash`, `blueprint_schema`, `ai_cache` (config hash to text and created). Everything except `opted_out_at` and `ai_cache` can be rebuilt from markers and registries by `rebuild_index`. Config entry options hold GlobalSettings only. No secrets anywhere.

## 7. Self healing and reconcile

`async_reconcile()` runs after the Home Assistant started event, after every integration update, and from maintenance:

1. Adapter check; stop here with `adapter_incompatible` when it fails.
   After the started event only: fire `device_routines_timer_caught_up` for each routine timer the restore state shows ran out during the restart (decision L20).
2. Blueprint: missing, install; hash equals the shipped one, nothing; hash equals a previously shipped version, install (upgrade); anything else, `blueprint_modified`.
3. The `Routines` label and the `Device Routines` category exist with the right icon.
4. Ownership index: scan every automation; owned means M1 and M2; add missing entries, drop stale ones, detect detached ones.
5. For each owned automation: the target entity exists (else status `missing_target` and the routine off); helpers exist (else recreate; a weekly schedule raises `schedule_blocks_needed`); the automation entity loaded (else regenerate once, then `automation_load_failed`); the alias follows a device rename while it is still generated; the area follows when `assign_area` is on.
6. Opted in devices: label, entities and automations are consistent in both directions.
7. Cleanup: candidates older than `cleanup_after_days` lose their automation, timer, schedule helper and Store entries.
8. Summaries refreshed; Health published.

Event reactions, all routed through the manager: device registry update (rename, area change, removal), entity registry update (entity id change of a target or helper), label registry update, `automation_reloaded`, automation entity added or removed, blueprint reinstalled. The PRD 3.1 table is the behavioral contract; every row is a harness test.

## 8. Privacy architecture

- `.gitignore`, in the first commit: `CLAUDE.local.md`, `local/`, `*.local.*`, `.env`, `tests/fixtures/raw/`, `.deployed`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `htmlcov/`, `node_modules/`, `dist/`.
- `local/` holds raw captures (`local/captures/`), `local/anonymize_map.json`, `local/denylist.txt` and `local/live.env` (the Home Assistant URL and token for the live suite).
- `tools/make_denylist.py` builds `local/denylist.txt` from registry dumps in `local/captures/registries.json`: entity ids, device ids, device, area and floor names, aliases, hostnames, IP addresses, MAC addresses, user names and email addresses. The GitHub user name is allowed because the repository is public.
- `tools/anonymize.py` applies a deterministic mapping stored in `local/anonymize_map.json`, replacing every denylisted token with ids like `switch.example_plug_1` and names like Example plug 1 or Area 1, keeping times, domains, structure and automation shapes, and asserting that no denylisted token survives.
- `tools/privacy_check.py --staged` runs in the pre commit hook on staged files and the commit message against the denylist and the generic patterns; `--ci` runs the generic patterns only: Home Assistant long lived tokens, GitHub tokens, private IPv4 ranges, MAC addresses, `.local` hostnames, email addresses and 32 character hex ids outside `tests/fixtures/`. `tools/privacy_allowlist.txt` lists intentional examples.
- `tools/style_check.py` fails on the em dash character (U+2014) anywhere in the repository.
- PRD scenario S10 is automated in CI with a synthetic denylisted token on a throwaway branch.

## 9. Repository, tooling and CI

Layout per PRD 7.4 plus `tools/ha_package/`, `tools/make_denylist.py`, `tools/style_check.py`, `docs/decisions-log.md`, `docs/user-guide.md`, `docs/api.md`, `docs/stage0-report.md`, `.github/ISSUE_TEMPLATE/`, `.pre-commit-config.yaml`, `pyproject.toml` and `requirements_test.txt`.

- Python 3.13 locally (matching the core version Stage 0 validates); `ruff` with select ALL and a short documented ignore list, line length 100; `mypy --strict` on the component and `tools/`; `pytest` with `pytest-homeassistant-custom-component` pinned to the validated core; `hypothesis`; coverage fails under 95 percent for `custom_components/device_routines`.
- `.github/workflows/ci.yml` on push and pull request to `dev` and `main`, jobs: `lint`, `typecheck`, `test` (a matrix with the pinned core and the latest core, the latter as continue on error until it passes), `hassfest`, `hacs` (the HACS action), `privacy`, `style`, `deploy-tool-parity` (fetches `tools/ha_deploy.py` from the `ha-device-links` main branch and diffs; skipped when the sibling repository or file does not exist) and `promote` (needs every other job; runs only on push to `dev`; moves the `dev-stable` tag to the commit with a forced tag push; permissions `contents: write`).
- `.github/workflows/release.yml` on a `v*` tag: verifies that `manifest.json` carries the tag version, builds the console bundle (from Phase 4), zips `custom_components/device_routines` as `device_routines.zip`, creates the GitHub release with notes from `CHANGELOG.md`; a `-beta.N` tag becomes a pre release.
- Branches: `dev` is the working branch; `main` is protected (all CI jobs required, no force pushes, no deletions, linear history) and receives merges from `dev` at phase exits and for releases. Conventional commits; `CHANGELOG.md` in Keep a Changelog format; the version bump in `manifest.json` lands in the release commit.
- Dependabot for GitHub Actions and pip, monthly.

## 10. Deployment pipeline

### 10.1 tools/ha\_deploy.py

Standard library only, Python 3.11 compatible (the Home Assistant container interpreter), one file, version header `ha_deploy v1.1, shared with ha-device-links`.

```text
ha_deploy.py deploy   --domain device_routines --repo <owner>/ha-device-routines [--ref dev-stable] [--config /config]
ha_deploy.py rollback --domain device_routines [--config /config]
ha_deploy.py status   --domain device_routines [--config /config]
```

- `deploy`: resolve the ref through the GitHub commits API (sha, plus the branch or tag name); when `.deployed` already carries that sha, print `ok true, changed false` and exit 0; download the immutable archive for the sha from codeload; extract only `custom_components/<domain>`; run `compileall` on it; diff against the current directory to compute `changed_files`; copy the current directory to `<config>/.ha_deploy/<domain>/backups/<timestamp>-<old sha>` (keep five); swap through a staging directory with `os.replace`; write `.deployed` with commit, branch, deployed\_at, previous\_commit and changed\_files; print the JSON; exit 0. Any failure prints `ok false` with an error and exits 1, leaving the previous directory untouched.
- `restart_required` when any `.py`, `manifest.json`, `services.yaml`, `strings.json` or `translations/*` file changed; `reload_automations` when only `blueprints/*` changed; `browser_reload` when only `frontend/*` changed.
- `rollback`: restores the newest backup, writes `.deployed` with `rollback_of`, and refuses with exit code 2 when the last operation was already a rollback.
- `status`: prints `.deployed`, `hacs_managed` (true when the HACS store lists the domain), the backup list and `python_ok` (a compileall of the current directory).
- Never restarts, never reloads an entry, never writes to `.storage` or `automations.yaml`. Unit tests use a local tarball and a temporary config directory; network calls are injected.

### 10.2 tools/ha\_package/device\_routines\_dev.yaml

A Home Assistant package with `<owner>` as the only value to edit. Contents:

- `shell_command`: `deploy_device_routines` running `python3 /config/tools/ha_deploy.py deploy --domain device_routines --repo <owner>/ha-device-routines --ref <ref or dev-stable>`, `rollback_device_routines` and `device_routines_deploy_status`.
- A `rest` sensor `sensor.device_routines_dev_stable`: resource `https://api.github.com/repos/<owner>/ha-device-routines/git/ref/tags/dev-stable`, scan interval 600 seconds, value the first 12 characters of `object.sha`, header `Accept: application/vnd.github+json`.
- `input_boolean.device_routines_auto_deploy` (initial on), `input_boolean.device_routines_auto_restart` (initial off), `input_datetime.device_routines_restart_window_start` (03:00) and `input_datetime.device_routines_restart_window_end` (04:00).
- Automation Device Routines: deploy dev-stable. Trigger: state of the rest sensor. Condition: auto deploy on. Action: the deploy shell command with `response_variable`; when `changed`: `reload_automations` only, call `automation.reload`; `restart_required`, create the persistent notification `device_routines_deploy` and, when auto restart is on and the time is inside the window, call `homeassistant.restart`; `browser_reload` only, the notification says so.
- Automation Device Routines: restart window. Trigger: time at the window start. Conditions: auto restart on and a deploy pending (the notification exists, or the Health `commit` differs from the status output). Action: `homeassistant.restart`.
- Automation Device Routines: post restart check. Trigger: Home Assistant start; delay three minutes; when `sensor.device_routines_health` is still unavailable and the status output shows a deploy newer than the last successful load: `rollback_device_routines` and a notification saying rolled back, restart needed.

Claude Code never calls `homeassistant.restart`. The automations above are the only callers, and only when Jayant has turned the switch on.

### 10.3 Health contract

`sensor.device_routines_health`: state `ok` (all checks pass), `degraded` (blueprint modified, an automation failed to load, or an adapter fallback is active) or `error` (adapter incompatible). Attributes: `version`, `commit`, `branch`, `deployed_at`, `channel`, `blueprint_schema`, `blueprint_status` (ok, modified, missing), `owned_count`, `loaded_count`, `issues`, `ha_version`, `last_reconcile`.

### 10.4 Stable channel

HACS custom repository until the default submission; `hacs.json` per PRD 11.1; releases carry `device_routines.zip`. The HACS update entity plus an optional user automation can auto install; the restart decision belongs to each user.

### 10.5 Claude Code loop

PRD 11.2 as amended: push to `dev`; wait for green and the `dev-stable` move, or trigger the deploy shell command over MCP to skip the poll; never restart; after Jayant's restart poll Health until `commit` matches; run `pytest -m live`; check Repairs; on failure roll back, say a restart is needed, and write a regression test.

## 11. Testing specification

### 11.1 Layout

`tests/unit/` (pure modules), `tests/golden/` (corpus and expected lines), `tests/blueprint/` (behavior matrix), `tests/integration/` (flows, entities, adapter, manager, repairs, WebSocket), `tests/tools/` (deploy, privacy, anonymize, style), `tests/live/` (read only, marker `live`, skipped without `local/live.env`), `tests/fixtures/` (anonymized only).

### 11.2 Behavior matrix

Every row is a harness test with time travel; the ids are stable and the Implementation plan assigns them to phases.

| Ids | Covers |
| --- | --- |
| B01 to B05 | Window on and off same day; window crossing midnight; crossing window with a weekday set and the start day rule; weekends only; some days |
| B06, B07 | Weekly schedule blocks; adjacent blocks at midnight produce no blip |
| B08 | One shot start with the docked guard |
| B09 to B13 | Turn off after from a manual on; cancelled by a manual off; survives a restart; not applied inside an explicit window; applied after an on without an off |
| B14 to B17 | Keep alive after a device originated off; never during a scheduled off; cancelled by an on; survives a restart |
| B18 | D27 rejection of both durations |
| B19 to B22 | Catch up on start inside a window; on reconnect; one shot late start inside the window; one shot outside the window waits |
| B23 to B26 | Manual change sets override and suppresses catch up; a scheduled time clears override; a person clears override and catch up runs; respect manual off sets no override |
| B27 to B30 | Pause blocks scheduled and countdown actions and fires the event; pause pauses and resumes a running timer with the remaining time; pause end catch up (D20); resume |
| B31 to B34 | Skip next on a window start skips both ends (D18); on a window end (D19); on a running countdown; pressing twice extends |
| B35, B36 | Manual change while paused sets no override (D21); routine off runs nothing and keeps the pause |
| B37, B38 | Pulse; pulse interrupted by a restart repaired by catch up |
| B39 | Refused actions never fire for any generated input |
| B40, B41 | DST spring forward; DST fall back |
| B42 | A queued burst is processed in order |
| B43 | Integration disabled, the routine still runs |
| B44 to B46 | Attribution: a time triggered automation change is not manual; a wall switch change is manual; an app change is manual |

### 11.3 Integration tests

Zero field config flow; the suggestions step; options; label sync both ways; entities per domain; the write path writes `automations.yaml` with M1 to M8; sync back, valid and invalid; the lookalike guard (S7); take control (detached); deletion; removal with keep and with delete; helper creation and recreation; cleanup after the period with time travel; a target entity id rename; a device rename; a device removal; blueprint missing, modified and upgraded; schema migration of owned automations; Store migration; actions with device, area, label and entity targets and the ignored list (S13); integration triggers and conditions; the Repairs catalog; diagnostics redaction; the WebSocket contract for every command; hub sensors; Health with and without `.deployed`; the AST import rule test.

### 11.4 Golden corpus

At least 25 anonymized automations from Stage 0 plus synthetic ones covering every grammar rule and every known unsupported construct. Each has an expected lines file; any difference fails. G5 target: at least 90 percent of items parsed and zero wrong lines, reviewed once by Jayant in Phase 1.

### 11.5 Property tests

Compiler round trip in both directions; refusals never produced; the sentence length cap; next run within one week and monotonic; the skip target equals the sentence's action.

### 11.6 Live suite (read only)

Schedule sensors exist where expected; owned automations carry M1 to M8; the share of `source: none` lines; Health `commit` equals the deployed sha; no open Repairs issues from this integration; the adapter report is clean.

### 11.7 Acceptance scenarios

PRD 13.4 S1 to S13 are mapped to phases in the Implementation plan; each live write scenario runs with a read before and after (pre approved since decision L26).

## 12. Performance, limits, security

- No polling anywhere in the integration; recompute is event driven and debounced; one point in time listener per device.
- Bounded structures: the attribution map holds 10,000 entries; the AI cache is pruned to known hashes; debounce queues are per device.
- A home with 100 routines has 100 automations, at most 100 timers, at most 100 schedule helpers, 100 override switches, 100 Paused until entities and Schedule sensors per scope.
- Security: no outbound calls from the integration (the AI Task entity is one the user chose on their own instance); no stored secrets; WebSocket writes require admin; actions follow Home Assistant permissions; refused actions are enforced in the compiler, on sync back and in the blueprint guards.

## 13. Defaults applied here

- Minimum Home Assistant version: the one Stage 0 validates, recorded in `hacs.json`, `manifest.json` and the blueprint.
- Python 3.13 locally; the deploy tool stays 3.11 compatible.
- Console (Phase 4): Lit and TypeScript, built with Vite into one bundle under `frontend/dist/`, served by `panel_custom` with `require_admin: true`, cache busted by version; vitest for tests. Nothing of this is needed before Phase 4.
- Everything else follows the PRD decision register; new design level choices go to `docs/decisions-log.md` with a PRD register entry in the same pull request.
