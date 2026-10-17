# Stage 0 report

One section per Stage 0 item of IMPLEMENTATION_PLAN Section 2, in the format of template
9.2. The plan for each item is written here before it runs. Evidence names only what the
public repository already names (the package's own helpers, sensors and automations);
nothing here describes the instance's devices, areas or automations. Times are UTC.

## V11: the development channel works end to end (Phase 0 task 0.10)

### Plan

| Field | Content |
| --- | --- |
| What | A commit pushed to `dev` reaches the running instance with no human step except the restart, and a rollback restores the previous commit. |
| How | Push a trivial change inside the component (a comment in `const.py`, so the deploy reports `restart_required`); watch CI and the `dev-stable` promotion; watch `sensor.device_routines_dev_stable` change and the deploy automation run (its trace); read the notification; ask the owner to restart; poll `sensor.device_routines_health` until `commit` equals the sha; call `shell_command.rollback_device_routines`; ask for a restart; confirm Health shows the previous commit; deploy again with `shell_command.deploy_device_routines`; ask for a final restart and confirm Health is back on the new commit. |
| What proves it | The Health sensor's `commit` attribute equal to the pushed sha, then to the previous sha after the rollback, then to the pushed sha again. |
| What restores it | The final deploy and restart leave the instance on the head of `dev`, which is the state the loop maintains anyway. |
| Approval | The two restarts are the owner's; the rollback and the manual deploy are part of the task as the plan describes it. |

### Starting state (read only, verification half of task 0.9)

| Time | Observation |
| --- | --- |
| 2026-10-14T22:50Z | `shell_command.deploy_device_routines`, `shell_command.rollback_device_routines` and `shell_command.device_routines_deploy_status` are registered. |
| 2026-10-14T22:50Z | `sensor.device_routines_dev_stable` reads `82c053bc58a1`, the head of `dev` and the target of the `dev-stable` tag. |
| 2026-10-14T22:50Z | The helpers exist: auto deploy on, auto restart off, the window 03:00 to 04:00, last good commit `82c053b`. |
| 2026-10-14T22:50Z | The three automations exist and are on: deploy dev-stable, restart window, post restart check. The post restart check ran at the start and recorded the last good commit. |
| 2026-10-14T22:50Z | `sensor.device_routines_health` is `ok` on commit `82c053b`, channel `dev`, version 0.0.1. |

### Steps

| Time | Step | Evidence |
| --- | --- | --- |
| 22:54:07 | Push of `870d343` to `dev` (the V11 plan and a comment in `const.py`) | Every pre commit hook passed |
| 22:55:49 | CI run 38650720726 green; `promote` moved `dev-stable` | Every job succeeded (lint, typecheck, test pinned and latest, hassfest, hacs, privacy, style, deploy-tool-parity, promote); the tag resolves to `870d343` |
| 22:58:48 | `sensor.device_routines_dev_stable` changed to `870d343fd2bc` on its own poll, three minutes after the promotion | Sensor `last_changed` |
| 22:58:48 to 22:58:49 | The deploy automation ran (trace `84baaa9c`, state stopped, finished) | The tool returned `ok`, `changed`, commit `870d343`, previous `82c053b`, `changed_files` `["const.py"]`, `restart_required` true, `hacs_managed` false, no warnings; the choose took the restart branch; auto restart is off, so no restart was attempted |
| 22:58:49 | Notification `device_routines_deploy` | "Device Routines 870d343fd2bc deployed; restart Home Assistant to load it. Changed: const.py." |
| 23:33:56 | Owner restart 1. `sensor.device_routines_health` came up `ok` | `commit` `870d343`, `deployed_at` 22:58:49Z, channel `dev`: equal to the pushed sha |
| 23:34:06 to 23:37:06 | The post restart check ran from the start event (trace `b1cd7bbc`) | After the three minute delay its state condition saw `ok` and stopped: no rollback. Finding: the `to: ok` trigger never fired, because Health turned `ok` ten seconds before the start event and automations arm their triggers only at that event, so the last good commit stayed `82c053b`. Fixed in the package, decision L16 |
| 23:38 | Read before the rollback: `shell_command.device_routines_deploy_status` | Deployed `870d343`, previous `82c053b`, `rollback_of` null, one backup `...-82c053bc58a1`, `python_ok` true, `hacs_managed` false |
| 23:38 | `shell_command.rollback_device_routines` over MCP | `ok`, `changed`, commit `82c053b`, previous `870d343`, `changed_files` `["const.py"]`, `restart_required` true |
| 23:44:54 | Owner restart 2. Health came up `ok` | `commit` `82c053b`, `deployed_at` 23:39:23Z: the rollback is running. The start event followed at 23:45:05, the same order as restart 1, which confirms the L16 finding |
| 23:47:23 | Deploy again: push of `8420882` (the L16 fix) to `dev` | Hooks passed |
| 23:49:12 | CI run 38656209295 green; `dev-stable` moved to `8420882` | Every job succeeded |
| 23:54:49 | `sensor.device_routines_dev_stable` read `842088276435`; the deploy automation ran (trace `328127f0`) | `ok`, `changed`, commit `8420882`, previous `82c053b` (the rolled back code), `changed_files` `["const.py"]`, `restart_required` true; notification "Device Routines 842088276435 deployed; restart Home Assistant to load it." Finding: the `short_sha` variable rendered as an integer because that prefix is all digits (decision L18) |

The instance now runs `82c053b` with `8420882` deployed and waiting for a restart, which
is the normal resting state of the loop between a deploy and a restart. The next restart
loads the newest deployed commit.

### Record

| Field | Content |
| --- | --- |
| Assumption | The development channel of PRD 11.2 and TECH_SPEC 10: a green push to `dev` reaches the instance with no human step except the restart, and a rollback restores the previous commit |
| Item | V11 |
| Status | closed, with three amendments to the package |
| Evidence | The steps table above: Health `commit` went `82c053b`, then `870d343` (the push) after restart 1, then `82c053b` (the rollback) after restart 2; the loop deployed `8420882` by itself 5 minutes 37 seconds after its promotion |
| Consequence | Decisions L16 (the post restart check records a load during startup and runs in parallel mode), L17 (the first tag reading after a start never deploys, so a restart cannot undo a rollback) and L18 (sha prefixes are sliced inside message templates). The installed package must be replaced once with the new file and automations reloaded; no restart is needed for that. TECH_SPEC 10.2 is unchanged in intent; the package is its implementation |
| Fixtures | none |

## V2: automation configs and reference helper results (A3, A4)

### Plan

| Field | Content |
| --- | --- |
| What | For every automation on the instance: the config its loaded entity exposes, the reference helper results, and how a YAML defined automation appears. |
| How | Read only, over MCP: the `automation/config` WebSocket command (it returns the loaded entity's `raw_config`) for every automation entity; the `search/related` WebSocket command, which runs the automation component's reference helpers, for every automation; the config REST endpoint (`ha_config_get_automation`) for comparison. Raw results to `local/captures/automations/` (not tracked); `tools/scrub_automations.py` then `tools/anonymize.py` into `tests/fixtures/automations/`. |
| What proves it | Configs returned for automations the REST endpoint cannot see; helper results that list the entities and devices each automation targets. |
| What restores it | Nothing to restore: no write. |

### Evidence

| Observation | Detail |
| --- | --- |
| Automation entities | 43: 39 defined in the UI, the 3 of the development package (YAML, in a package), and 1 registry entry restored as `unavailable` with no config behind it. |
| A4: configs of YAML automations | `automation/config` returned the full config of every loaded automation, the package automations included. The REST endpoint answered "not found" for the package automations: it reads `automations.yaml` only, exactly as the PRD expected. |
| A4: a duplicate id | The system log holds "ID ... already exists - ignoring" for one automation id defined twice; the ignored copy has no entity and is visible to neither path. |
| A4: an orphaned entity | The restored, `unavailable` entity has no config: `automation/config` answers "Entity not found". Discovery must skip it. |
| A3: entity targets | `search/related` resolved entity targets, including the new target style (`switch.is_on` conditions with `target`, `event.received` triggers with `target`), and the YAML package automations. |
| A3: device triggers, conditions and actions | `search/related` failed with `unknown_error` on all 3 automations whose device triggers, conditions and actions name the entity by registry id. Reading the pinned core: `entities_in_automation` returns those registry ids unchanged and the search component calls `split_entity_id` on them. `automations_with_device` still finds these automations by `device_id`. |
| A3: what the helpers miss | Entities named only inside templates (several automations read helpers through `states()`, `is_state()` or `state_attr()`) never appear in the helper results. Script calls (`script.x` as an action) are not entity references either. |
| A3: area and label targets | No automation on the instance targets an area or a label, so these two paths cannot be shown live. They are core helpers with core tests; Phase 1 covers them in the harness against the pinned core. |
| Corpus shapes | Time windows with a reconcile on start, run timers through `for:`, an off then on cycle with a delay, `timer.finished` and `schedule.block_*` triggers, template guards, device triggers, multi automation controllers with helpers and scripts, a webhook with no actions, notification only automations. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A3 (the reference helpers find automations that target a device's entities directly, through the device, its area or a label, YAML included) and A4 (the loaded automation entity exposes its full config for UI and YAML automations) |
| Item | V2 |
| Status | A4 closed. A3 amended: entity and device paths closed live, area and label paths deferred to the Phase 1 harness, and entity references may be registry ids |
| Evidence | The table above; raw captures in `local/captures/automations/` (private) |
| Consequence | TECH_SPEC 4.2, the "Read automation configs and references" row: resolve registry id references through the entity registry, keep action targets only, skip automation entities without a config, treat template only references as invisible. Never call `split_entity_id` on a raw reference |
| Fixtures | `tests/fixtures/automations/automation_01.json` to `automation_39.json`: config and, where the helpers answered, the related entities, devices, areas, floors and labels. `tests/golden/test_corpus.py` validates each against the pinned core |

## V4: AI Task availability (A12)

### Plan

| Field | Content |
| --- | --- |
| What | Whether `ai_task.generate_data` is usable on this instance with a locally hosted model. |
| How | Read only: list `ai_task` entities, the `ai_task` services and the AI Task preferences. A `generate_data` call with a synthetic automation only if an entity exists. |
| What proves it | An AI Task entity and a structured answer to a synthetic prompt. |
| What restores it | Nothing to restore: no write. |

### Evidence

| Observation | Detail |
| --- | --- |
| Services | `ai_task.generate_data` and `ai_task.generate_image` are registered; `generate_data` takes `task_name`, `instructions`, an optional `entity_id` (AI Task entities with the generate data feature), `structure` and `attachments`. |
| Entities | No `ai_task` entity exists; the local LLM integration provides conversation agents only. |
| Preferences | `ai_task/preferences/get` returns no default entity for data or images. |
| Call | Not made: without an entity the service has nothing to run on. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A12 (`ai_task.generate_data` is available and usable with a locally hosted model) |
| Item | V4 |
| Status | deferred: the service exists, no AI Task entity does |
| Evidence | The table above |
| Consequence | None for v1: AI summaries stay off by default (FR-S5, the default noted in the instance context). If an AI Task entity is created on the local endpoint later, V4 runs its `generate_data` call then |
| Fixtures | none |

## V10: restored expired timer, midnight schedule blocks, DST dates (A5b, A6, A7)

### Plan

| Field | Content |
| --- | --- |
| What | A5b: a timer restored with an end in the past fires a `timer.finished` that a routine sees. A6: schedule blocks that meet at midnight do not blip off and on. A7: what the time trigger does with a skipped and a repeated wall clock time. |
| How | Harness only, against the pinned core (`tests/stage0/test_v10_timer_restore.py`, `tests/stage0/test_v10_schedule_dst.py`). A5b: a cold start (`CoreState.not_running`) with a restore cache holding an active timer, three automations listening (the `timer.finished` event, the purpose specific `timer.finished` trigger, a start trigger), then `async_start`; a second case with time left. A6: a schedule with Monday 22:00 to 24:00 and Tuesday 00:00 to 02:00, walked minute by minute from 23:55 to 02:00 with state triggers to on and to off and the purpose specific block triggers. A7: a time trigger at 02:30 (or 01:30 in Los Angeles in the autumn) walked minute by minute through the night of each 2026 change in America/Los_Angeles and Europe/Berlin. |
| What proves it | The automation runs each probe records, and the state changes of the timer and the schedule. |
| What restores it | Nothing: no live write. The probes stay in the suite, so a core upgrade that changes any answer fails CI. |

The plans and the probes were written in the same commit; the probes are repeatable and
run on every push.

### Evidence

| Probe | Observation |
| --- | --- |
| A5b, end in the past | The core fires `timer.finished` once, while the entity is added during startup. Neither the event trigger nor the purpose specific trigger is armed yet: only the start automation runs. Afterwards the timer reads `idle` with `last_transition: finished`. |
| A5b, time left | The timer resumes as `active`; when it ends after startup, both triggers run. |
| A6 | The state stays `on` across midnight; one attribute only change (`next_event` moves to 02:00). State triggers to on and to off stay silent and `schedule.block_ended` does not fire. `schedule.block_started` does fire at midnight, by design for back to back blocks. At 02:00 the state turns off and both off triggers run. |
| A7, skipped (02:30 on 2026-03-08 in Los Angeles, 2026-03-29 in Berlin) | The trigger does not run that night at all. |
| A7, repeated (01:30 on 2026-11-01 in Los Angeles, 02:30 on 2026-10-25 in Berlin) | The trigger runs twice, first with the daylight saving offset, then an hour later with the standard offset. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A5b (a restored timer that expired while HA was down fires `timer.finished` at startup), A6 (adjacent blocks at midnight cause no blip), A7 (DST behavior known and documented) |
| Item | V10 |
| Status | A5b amended; A6 closed; A7 closed, with the spec corrected to the observed behavior |
| Evidence | The table above; seven harness tests |
| Consequence | A5b: decision L20, the integration catches a missed finish up from the restore state helper and the blueprint gets a second `timer_done` trigger on `device_routines_timer_caught_up` (TECH_SPEC 4.2, 5.3, 7). A6: the blueprint keeps state triggers for `block_on` and `block_off` and must not use `schedule.block_started` (TECH_SPEC 5.3 note). A7: decision L21, TECH_SPEC 3.6 rewritten |
| Fixtures | none (synthetic harness data) |

## V12: a datetime entity in time triggers and conditions (A13)

### Plan

| Field | Content |
| --- | --- |
| What | Whether the time trigger and the time condition accept a `datetime` entity; how a timestamp sensor compares; whether the TECH_SPEC 5.4 template fallback is correct; whether a restored `datetime` entity keeps its value. |
| How | Harness only (`tests/stage0/test_v12_datetime.py`): validate an automation with each construct; run a time trigger and a time condition on a timestamp sensor across its time; render the template for unknown, unavailable, past and future values; add a `datetime` entity that implements RestoreEntity over a restore cache. |
| What proves it | Validation errors or acceptance, automation runs, condition results, the restored state. |
| What restores it | Nothing: no live write. |

### Evidence

| Probe | Observation |
| --- | --- |
| Time trigger, `datetime` entity | Refused at validation: the trigger accepts `input_datetime` and `sensor` entities only. |
| Time condition, `datetime` entity | Refused at validation ("Invalid time specified"): the condition accepts `input_datetime`, `time` and `sensor` only. |
| Timestamp sensor | The trigger fires at the sensor's point in time. The condition compares only the local time of day: with the sensor at tomorrow 07:30, `after` is already true at 08:00 today. |
| Template fallback | Correct for all four values. |
| Restored `datetime` entity | The value comes back from the restore cache. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A13 (time triggers and conditions accept a `datetime` entity; a restored one keeps its value) |
| Item | V12 |
| Status | amended to the designed fallback, as PRD 9.5 expected |
| Evidence | The table above; eight harness tests |
| Consequence | Decision L22: Paused until stays a `datetime` entity; `not_paused` is the one template condition; `pause_ended` is omitted and the integration resumes at the stored time. The timestamp sensor alternative of PRD 9.5 is ruled out because the condition ignores the date. TECH_SPEC 5.3 and 5.4 updated |
| Fixtures | none |

## A3, area, floor and label paths (deferred from V2)

### Plan

| Field | Content |
| --- | --- |
| What | Whether the reference helpers find automations that target a device through its area, its floor or a label. |
| How | Harness only (`tests/stage0/test_a3_area_label.py`): synthetic registries with a living room fan on a device in an area on a floor with a label, and automations targeting each id, plus one that targets the area with another domain's action. |
| What proves it | The helper results for each id. |
| What restores it | Nothing: no live write. |

### Evidence

| Helper | Observation |
| --- | --- |
| `automations_with_area`, `_floor`, `_label` | Each finds the automations that name that id, and only those. |
| `automations_with_entity`, `_device` | Blind to area, floor and label targets: they list literal references only. |
| `areas_in_automation` | Lists an area targeted by a `light.turn_on` action next to a fan's area: the helpers do not look at the action's domain. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A3, the area and label part |
| Item | V2 (deferred part) |
| Status | closed |
| Evidence | The table above; one harness test |
| Consequence | TECH_SPEC 4.2, the read row: discovery for a device asks `automations_with_area` for the device's area and each entity's own area, `automations_with_floor` for those areas' floors, and `automations_with_label` for the device's and the entities' labels, then keeps only actions whose domain matches one of the device's entities |
| Fixtures | none |

## V3: contexts of automation, app, voice and physical changes (A9 as amended)

### Plan

| Field | Content |
| --- | --- |
| What | A time triggered automation run creates a parentless context, its `automation_triggered` event carries the context its actions use, and the resulting `state_changed` carries the same context; physical, app and voice changes never reuse such a context. |
| How | Write (approved for the Stage 0 write items in plan order): one `stage0_v3_time_probe` automation with two time triggers a minute apart on the sandbox Matter plug, turning it on, then off. Read the run traces (context of each run), the plug's state contexts after each run, and the logbook entries (which link a state change to the event that caused it). Also read, read only, the plug's logbook for the previous days, where its hand written time window automation ran. Raw results to `local/captures/v3/`. The by hand, app and voice part needs the owner operating four devices and is recorded as a cleanup item. |
| What proves it | Each run's trace context equals the context of the state change it caused, with `parent_id` and `user_id` null. |
| What restores it | The automation is deleted; the plug ends off, as it was before, which a final read proves. Its hand automation is untouched: it reacts only to 17:00, 09:00, a start and a return from unavailable. |

## V5: install a blueprint and validate its features (A1, A8)

### Plan

| Field | Content |
| --- | --- |
| What | A1: a blueprint installed by code is usable at once, with no restart. A8: sections, a `condition` selector, `enabled: !input` on a trigger and a condition, the sentinel pattern, and the purpose specific `timer.finished` trigger. |
| How | Harness (`tests/stage0/test_v5_blueprint.py`): install `tests/fixtures/stage0/stage0_probe.yaml` through the automation component's `DomainBlueprints.async_add_blueprint`, the method TECH_SPEC 4.2 names, validate a `use_blueprint` automation, reload and run it. Live (write, approved for the Stage 0 write items): save the same file as `stage0/stage0_probe.yaml` with the `blueprint/save` WebSocket command, which calls that same method; read it back with `blueprint/list`; V6 then creates an automation from it. The throwaway integration of the plan is not used: a new custom integration loads only at a restart, which this session never does, and the WebSocket command runs the identical core path. |
| What proves it | The blueprint listed with its inputs and sections right after the save; an automation built from it validating and loading with `enabled: false` on the bound trigger and condition. |
| What restores it | V6 and V8 delete the automations built on it, then the blueprint is deleted and `blueprint/list` read again. The probe's actions only fire a `stage0_probe_ran` event; it never acts on a device. |

### Evidence

| Time | Observation |
| --- | --- |
| 19:10 | Read before: `blueprint/list` holds one core example blueprint and nothing under `stage0/`. |
| 19:11 | `blueprint/save` of `stage0/stage0_probe.yaml`: `overrides_existing: false`. Read straight back with no reload: the four sections (Target, Schedule, Timers collapsed, Advanced collapsed), the `condition` selector with default `[]`, the sentinel defaults, `used_by: []`. |
| 19:17 | `stage0_v6_probe` built on it loaded with state `on`. Its resolved config (`automation/config`): `enabled: false` on the time trigger and on the guard condition, the purpose specific `timer.finished` trigger on the sentinel `timer.device_routines_unused`, an empty `and` for the condition selector. |
| 19:17:42 | Firing `device_routines_timer_caught_up` ran it through the template condition and the empty extra conditions (trace `5925cdcf`, finished). |
| 19:17 | After the V6 update with `guard_enabled: true` the same condition reads `enabled: true`. |
| Harness | Four tests: install through `DomainBlueprints.async_add_blueprint`, sections kept, enabled inputs both ways, a reload picks up an automation built on the new blueprint. |
| Not done | Whether the editor renders the sections and the condition selector: no browser session to the instance (cleanup item C3, one look by the owner). |

### Record

| Field | Content |
| --- | --- |
| Assumption | A1 (an integration installs a blueprint and HA picks it up without a restart) and A8 (`enabled:` bound to inputs, a `condition` selector, collapsible sections) |
| Item | V5 |
| Status | A1 closed; A8 closed for validation and runtime, the form's rendering deferred to a look by the owner (C3) |
| Evidence | The table above |
| Consequence | None: TECH_SPEC 4.2's install path is the method the WebSocket command uses, and a blueprint saved that way is usable at once. The purpose specific `timer.finished` trigger exists and accepts a sentinel, so 5.3 uses it (decision L20) |
| Fixtures | `tests/fixtures/stage0/stage0_probe.yaml` (synthetic) |

## V6: create, update and delete one automation through the write path (A2)

### Plan

| Field | Content |
| --- | --- |
| What | A write path for one automation exists, it uses the editor's locking or an equivalent, and reloading that one automation leaves every other one running. |
| How | Source reading of the pinned core for the editor's lock. Live (write, approved): the config endpoint the editor itself uses (`POST /api/config/automation/config/<id>`, then its reload of that id only) creates `stage0_v6_probe` from the V5 blueprint, updates it and deletes it. Beforehand a second throwaway, `stage0_v6_long_run`, is started into a ten minute delay so that one run is in flight. Before and after each write: `current` of the long run, and `last_changed` of every other automation entity. Harness (`tests/stage0/test_v6_write_path.py`): the TECH_SPEC 4.2 primary path from code (load `automations.yaml`, replace one entry, write atomically, `automation.reload` with `id`) with a run in flight in another automation. |
| What proves it | `current` stays 1 on the long run through every write; no other automation entity changes `last_changed`; the probe appears, changes and disappears. |
| What restores it | Both throwaways deleted; a final read lists no `stage0_` automation. |

### Evidence

| Time | Observation |
| --- | --- |
| Source | The editor's lock is `BaseEditConfigView.mutation_lock`, an attribute of the HTTP view object, reachable only through the aiohttp router: not reachable in any supported way. The editor's write is load, replace one entry, `write_utf8_file_atomic`, then `automation.reload` with `id`; its delete also removes the entity registry entry. |
| 19:16 | Read before: 43 automations, none running, the newest `last_changed` 18:11:01Z (the restart). |
| 19:16:42 | `stage0_v6_long_run` created and started: `current: 1` in a ten minute delay. |
| 19:17 | Create of `stage0_v6_probe` through the config endpoint: `result: ok`; long run still `current: 1`. |
| 19:17:57 | Update of the probe: `result: ok`, the change visible in its config; long run `current: 1`; the 43 others' newest `last_changed` still 18:11:01Z. |
| 19:18:18 | Delete of the probe: entity and registry entry gone; long run `current: 1`; others unchanged. |
| 19:18 | Long run deleted; read after: no `stage0_` automation, 43 automations as before. |
| Harness | Three tests of the TECH_SPEC 4.2 path from code: create, update and delete with a run in flight elsewhere, which survives each; a full reload also leaves an unchanged automation's run alone; rewriting the running automation itself stops its run. A reload after removing the entry leaves a restored `unavailable` entity until the registry entry is removed. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A2 (a stable write path from integration code with the editor's locking; reloading one automation does not restart the others) |
| Item | V6 |
| Status | amended: the write path and the per id reload hold, live and in the harness; the editor's lock is not reachable |
| Evidence | The table above |
| Consequence | TECH_SPEC 4.2 write row: the adapter uses its own lock and the file hash compare with one retry (already the stated alternative), and a delete also removes the entity registry entry. Rewriting a routine stops its own in flight run, which only matters for a pulse in its delay; catch up repairs it, as for a restart |
| Fixtures | none |

### Evidence

| Time | Observation |
| --- | --- |
| 19:06 | Read before: the plug `off`, its hand automation on; no automation run in flight. Its logbook for the previous days links its 17:00 and 09:00 changes to `automation_triggered` from a `time` source. |
| 19:08 | `stage0_v3_time_probe` created through the config endpoint (`result: ok`). |
| 19:14:00 | Run 1 (trigger `time`): trace context `01M55MJ2...`, `parent_id` null, `user_id` null. The plug turned `on` with context `01M55MJ2...`, the same id. The logbook's `automation_triggered` entry carries `context_id` `01M55MJ2...`. |
| 19:15:00 | Run 2: `automation_triggered` with context `01M55MKW...`; the plug turned `off` with context `01M55MKW...`, parent and user null. |
| 19:15 | The probe deleted; read after: no `stage0_` automation, the plug `off` as before. |
| Not done | Changes by hand, by app and by voice on a Z-Wave, a Zigbee, a Matter and a Wi-Fi device: they need the owner operating the devices (cleanup item C2). No `script_started` was recorded either: the probe had no script (cleanup item C2). |

### Record

| Field | Content |
| --- | --- |
| Assumption | A9 as amended (every automation and script run emits an event carrying the context its actions use; physical, app and voice changes never reuse such a context) |
| Item | V3 |
| Status | closed for time triggered automation runs; the by hand, app and voice recordings deferred to the cleanup phase (they need the owner) |
| Evidence | The table above; raw capture `local/captures/v3/` (private) |
| Consequence | None to the design: the run's context is parentless and userless, exactly like a wall switch, and the state change reuses the run's context id, so the event map of TECH_SPEC 4.3 is what tells them apart, as designed (D26) |
| Fixtures | `tests/fixtures/attribution/v3_time_triggered.json`, checked by `tests/stage0/test_v3_contexts.py`; Phase 2 replays it through `attribution.py` |

## V7: timer and schedule helpers with a chosen entity id and the label (A5)

### Plan

| Field | Content |
| --- | --- |
| What | Timer and schedule helpers can be created from integration code, given a chosen entity id and a label, and removed. |
| How | Source reading of the pinned core for the storage collections TECH_SPEC 4.2 names. Harness (`tests/stage0/test_v7_helpers.py`): dispatch `timer/create` and `schedule/create` in process through an `ActiveConnection` for a system administrator user, then set the entity id and the label in the entity registry, then delete. Live (write, approved): the same commands over the API: a `stage0_v7_timer` (30 minutes, restore on) and a `stage0_v7_schedule`, a throwaway label `stage0_routines`, a registry rename of each to a chosen id, then deletion of all three. |
| What proves it | Each helper under its chosen entity id with the label; then gone. |
| What restores it | Both helpers and the label deleted; a read proves none of them is left. |

### Evidence

| Time | Observation |
| --- | --- |
| Source | Each storage collection is a local variable of its component's `async_setup`, referenced only by its WebSocket handlers and its entity lifecycle listener: TECH_SPEC 4.2's primary path is not reachable from integration code. |
| Harness | Three tests: `timer/create` and `schedule/create` dispatched in process through `ActiveConnection.async_handle` for a system user in the administrators group succeed (async handlers run as background tasks); the registry then gives the chosen entity id and the label; `timer/delete` and `schedule/delete` remove them; a system user outside the administrators group is refused with `unauthorized`. |
| 19:23 | Read before: no `stage0_` entity except the V5 blueprint's update entity; no `stage0` label. |
| 19:23 | `stage0_routines` label created; `timer/create` gave `timer.stage0_v7_timer` (30 minutes, `restore: true`) and `schedule/create` gave `schedule.stage0_v7_schedule` with the two midnight blocks. Registry update renamed them to `timer.stage0_v7_routine_probe` and `schedule.stage0_v7_routine_probe` with the label; their states followed (`idle`, `restore: true`; `off`, `next_event` Monday 17:00). |
| 19:23:40 | Both deleted (`require_restart: false`) and the label deleted; read after: no `stage0_` entity besides the blueprint's update entity, no `stage0` label. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A5 (timer and schedule helpers can be created from integration code with a chosen entity id and label) |
| Item | V7 |
| Status | amended: creation, the chosen entity id and the label hold live and in the harness, but through the helpers' WebSocket commands dispatched in process, not the storage collections |
| Evidence | The table above |
| Consequence | Decision L23: the adapter creates a system administrator user once (`Device Routines`, id stored in the entry) and dispatches `timer/create`, `timer/update`, `timer/delete` and the `schedule/` equivalents through an in process `ActiveConnection`, then sets the entity id, label and device in the registry. TECH_SPEC 4.2 helper row updated. No token, no loopback, no restart |
| Fixtures | none |

## V8: take control of a blueprint automation (A11)

### Plan

| Field | Content |
| --- | --- |
| What | "Take control" keeps the automation id and removes `use_blueprint`; the resulting shape is what TECH_SPEC 4.2's detection reads. |
| How | Live (write, approved): `stage0_v8_probe` on the V5 blueprint; then take control the way the editor does it: the `blueprint/substitute` WebSocket command renders the inputs, and the rendered config is saved over the same id through the config endpoint. Read the automation's config and entity before and after. |
| What proves it | Same entity id and unique id after; no `use_blueprint`; the triggers, conditions and actions inlined with the input values substituted. |
| What restores it | The automation deleted, then the V5 blueprint deleted; reads prove both gone, including the blueprint's update entity. |

### Evidence

| Time | Observation |
| --- | --- |
| 19:24 | `stage0_v8_probe` created on the blueprint (`on_time` 03:00:00); its config holds `use_blueprint`; registry: unique id `stage0_v8_probe`, entity `automation.stage0_v8_probe`. |
| 19:24 | Take control (rendered with `blueprint/substitute`, saved over the same id): unique id and entity id unchanged; `use_blueprint` gone; alias and description kept; triggers, conditions and actions inlined with `03:00:00` and the target substituted and with `enabled: false` kept on the bound trigger and condition; the blueprint's `variables` block kept as is. |
| 19:24 | The blueprint still lists the converted automation in `used_by`, and keeps doing so until that automation is removed. |
| 19:24 | The automation deleted, then the blueprint deleted. Spook (installed on the instance) had created `update.stage0_probe` for the blueprint because it carried a `source_url`; the entity outlived the blueprint and its registry entry was removed. Read after (19:25): no `stage0_` entity of any domain, 43 automations, one core example blueprint, as before V5. |
| Not done | The editor's own Take control button was not clicked (no browser session to the instance); the rendering path is the same `blueprint/substitute` command the editor calls. One look by the owner is in cleanup item C3. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A11 ("Take control" keeps the automation id and removes `use_blueprint`) |
| Item | V8 |
| Status | closed |
| Evidence | The table above |
| Consequence | TECH_SPEC 4.2 detection stays (`use_blueprint` absent on an id with M1). Two notes: the converted automation keeps counting as a user of the blueprint, so reinstall and cleanup never rely on `used_by` being empty; and decision L24, the shipped blueprint carries no `source_url` |
| Fixtures | none |

## V9: attach an entity to another integration's device (A10)

### Plan

| Field | Content |
| --- | --- |
| What | An entity of this integration lands on a device of another integration and shows in that device page's Configuration card. |
| How | Harness (`tests/stage0/test_v9_attach.py`) against the pinned core: the ha-device-links approach (identifiers and name copied verbatim from the registry entry into `DeviceInfo`), the registry alternative (the entity's `device_id` set to the user's device), and the core's `config/device_registry/list_linked_devices` command. Read only on the live instance: how the sibling's entities sit today. The live write of the plan (a `stage0_` config entity on the sandbox device) needs entity code loaded, which needs a restart; it moves to the first live deploy that carries an entity (cleanup item C4). |
| What proves it | The device record the entity lands on, the device count, the entity id, and the linked device list. |
| What restores it | Nothing live was written. |

### Evidence

| Probe | Observation |
| --- | --- |
| Core change | Core 2026.10 makes identifiers unique per config entry only: a device record has one `config_entry_id`, `async_get_or_create` looks devices up within the calling entry, and the old multi entry devices were split into per entry records. |
| `DeviceInfo` with copied identifiers and name | The entity lands on a new record owned by this config entry that carries the user's identifiers; the user's record is untouched; one more device in the registry; the entity id follows the copied name (`switch.living_room_fan_routine`). |
| `DeviceInfo` with identifiers only | Same, but the record and the entity are named after the config entry title (`switch.device_routines_routine`): the name has to be copied. |
| Linked devices | `config/device_registry/list_linked_devices` for the user's device returns this integration's record: the core relates the two records for the frontend. |
| Registry `device_id` | Setting the entity's `device_id` to the user's device works until the platform adds the entity again (every load), when the core clears it: not usable. Removing the user's device leaves such an entity with no device. |
| Live, read only | The sibling integration on this instance currently has only its own hub device; no attached rule entity exists to look at. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A10 (entities from this integration attach to existing devices from other integrations and appear in their Configuration card) |
| Item | V9 |
| Status | amended in the harness; the device page placement deferred to a live look (C4) |
| Evidence | The table above; five harness tests |
| Consequence | Decision L25: entities use `DeviceInfo` with the identifiers and name copied verbatim from the user's device, which on core 2026.10 creates a linked record of this integration. TECH_SPEC 4.2 attach row rewritten. If the C4 look shows the linked record's entities are not on the user's device page, the fallback is decided then with the owner, because the device page placement is the product's main surface |
| Fixtures | none |

## V13: purpose specific triggers and conditions from a custom integration (A14)

### Plan

| Field | Content |
| --- | --- |
| What | A custom integration registers purpose specific triggers and conditions that the editor offers with device, area and label targets. |
| How | Harness (`tests/stage0/test_v13_triggers.py`): a throwaway custom integration in `tests/fixtures/stage0/custom_components/stage0_probe/` with `trigger.py`, `condition.py`, `triggers.yaml` and `conditions.yaml`, loaded from the `custom_components` namespace path the way a HACS install is; read the descriptions the editor's pickers use; validate and run automations with a device, an area and a label target. The live half (the throwaway integration on the instance) needs a restart to load a new integration, which this session never does: the pickers are checked live once Device Routines ships its own triggers (cleanup item C5). |
| What proves it | Both in the core's description lists with their target selector; automations using each target kind validate, fire and pass. |
| What restores it | Nothing live was written. |

### Evidence

| Probe | Observation |
| --- | --- |
| Registration | Loading the custom integration registers `stage0_probe.routine_started` and `stage0_probe.routine_active` through the same integration platform processing as core integrations; nothing distinguishes a custom domain. |
| Descriptions | `trigger.async_get_all_descriptions` and `condition.async_get_all_descriptions` return each with `target: {entity: [{domain: [switch]}]}` and the `behavior` field: the data the editor's pickers render. |
| Targets | With a `device_id`, an `area_id` and a `label_id` target, each automation validates, its trigger fires on the switch turning on, and its condition passes. |

### Record

| Field | Content |
| --- | --- |
| Assumption | A14 (a custom integration can register purpose specific triggers and conditions that appear in the automation editor with device, area and label targets) |
| Item | V13 |
| Status | closed for the core; the editor's picker rendering deferred to a live look (C5) |
| Evidence | The table above; four harness tests |
| Consequence | None to the design: Phase 3's triggers and conditions follow the core shape (`async_get_triggers`, `async_get_conditions`, the two YAML files) |
| Fixtures | `tests/fixtures/stage0/custom_components/stage0_probe/` (synthetic) |

## Development package check (L16 to L18 installed?)

Read only, 2026-10-17 at 18:57Z, after the owner reported replacing the package and
reloading automations. The loaded configs (`automation/config`) and the entity attributes
still show the previous package: the post restart check runs in `queued` mode, the deploy
trigger has `not_to` but no `not_from`, and the deploy automation still sets `short_sha`
in `variables`. Every package automation's `last_changed` is the 18:10:52Z restart, so no
automation reload has happened since, and the post restart check's start run at 18:11Z
took the queued path. `input_text.device_routines_last_good_commit` still reads `82c053b`
while Health runs `797e0c4`, which is the stale value L16 fixes. The deploy loop itself
works; the risk until the new package is in place is the L17 case (a restart after a
rollback redeploys the rolled back commit). Cleanup item C1.

## Summary

| Assumption | Item | Status | Where the design changed |
| --- | --- | --- | --- |
| A1 blueprint installed by code, no restart | V5 | closed | TECH_SPEC 4.2 install row names the exact call |
| A2 write path, per id reload | V6 | amended: the editor's lock is not reachable | TECH_SPEC 4.2 write row: own lock and hash compare, registry removal on delete |
| A3 reference helpers | V2, harness | closed (entity, device, area, floor, label), with V2's registry id amendment | TECH_SPEC 4.2 read row |
| A4 loaded entity exposes its config | V2 | closed | none |
| A5 helpers from code with id and label | V7 | amended: through the WebSocket commands in process | TECH_SPEC 4.2 helper row, decision L23 |
| A5b restored expired timer fires | V10 | amended: it finishes before triggers are armed | TECH_SPEC 4.2, 5.3, 7, decision L20 |
| A6 midnight blocks | V10 | closed | TECH_SPEC 5.3 note: state triggers only |
| A7 DST behavior known | V10 | closed, spec corrected | TECH_SPEC 3.6, decision L21 |
| A8 blueprint features | V5 | closed for validation and runtime; form rendering to C3 | none |
| A9 contexts (amended in v1.1) | V3 | closed for time triggered runs; by hand, app and voice to C2 | none |
| A10 attach to another integration's device | V9 | amended in the harness; device page placement to C4 | TECH_SPEC 4.2 attach row, decision L25 |
| A11 take control keeps the id | V8 | closed | none (decision L24 from the same probe) |
| A12 AI Task | V4 | deferred (no AI Task entity) | none; AI summaries off for v1 |
| A13 datetime in time triggers and conditions | V12 | amended to the designed fallback | TECH_SPEC 5.3, 5.4, decision L22 |
| A14 custom purpose specific triggers and conditions | V13 | closed for the core; picker rendering to C5 | none |

Every throwaway artifact (`stage0_v3_time_probe`, `stage0_v6_long_run`,
`stage0_v6_probe`, `stage0_v8_probe`, the `stage0/stage0_probe.yaml` blueprint and its
Spook update entity, `timer` and `schedule` `stage0_v7_*`, the `stage0_routines` label)
was removed; the final read at 19:25Z found no `stage0` entity, automation, blueprint or
label. The sandbox plug ended `off`, as it started.

## Decision defaults applied

- PRD defaults D1 to D34 apply unchanged. D2(a), internals through one adapter, holds; its
  fallback (b) is no longer needed for helpers (L23).
- Instance context defaults: AI summaries off for v1; keep alive in minutes only; the
  sandbox plug was used for V3 under the owner's blanket approval of the Stage 0 write
  items in plan order (2026-10-17).
- The throwaway integration of V5, V6 and V13 was replaced by core paths reachable without
  a restart (`blueprint/save`, the config endpoint) and by a harness integration, because
  loading a new custom integration needs a restart, which no session does.
- The harness moved to core 2026.10.2, the instance's version, and HACS requires it.

## Cleanup items (need the owner)

| Id | Item | What it needs | When |
| --- | --- | --- | --- |
| C1 | Install the L16 to L18 package: copy `tools/ha_package/device_routines_dev.yaml` over the installed package file and reload automations; then a session confirms over MCP `mode: parallel`, `not_from` on the deploy trigger, no `short_sha` variable, and after the next restart that the last good commit follows Health | Owner, file copy and a reload (no restart) | Before the next restart |
| C2 | V3 by hand, by app and by voice on one Z-Wave, one Zigbee, one Matter and one Wi-Fi device (instance question 5), plus one script run, recorded and anonymized into `tests/fixtures/attribution/` | Owner names the devices and operates them while a session records | Before Phase 2's attribution task |
| C3 | One look at the blueprint form (sections, condition selector) and the editor's Take control button | Owner, a few minutes in the UI, when the Phase 2 blueprint is installed | Phase 2 |
| C4 | Device page placement of a linked record's entities (A10, L25) | A deploy carrying the first entity, then a restart, then one look at a device page | First Phase 1 live deploy |
| C5 | The editor's pickers show Device Routines triggers and conditions with device, area and label targets | A deploy carrying them, a restart, one look | Phase 3 |
| C6 | V4: an AI Task entity on the local endpoint, then one `generate_data` call (optional) | Owner creates the entity | Any time; AI summaries stay off until then |

## Exit

Every assumption is closed, amended or deferred; the write items ran under the owner's
blanket approval and the parts that need the owner are the cleanup items above; fixtures
were committed only after anonymization and the privacy check; TECH_SPEC follows every
amendment. Stage 0 is complete.
