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
