# Phase 2 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 4 (Build A, Phase 2 rows) and
Section 5 (live validation A), in the format of template 9.1. Evidence is quoted as the
tools print it, without instance names. Phase 3 rows of the same build are in
`phase-3.md`.

## Build A deploy stance (plan Section 0.1.6)

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Auto deploy off while Build A is open | Read before over MCP; `input_boolean.turn_off` on the auto deploy switch; read after; `shell_command.device_routines_deploy_status` (read only) | Before: auto deploy `on`, auto restart `off`, Health `ok` on `d00fa2f` (running), `dev-stable` at `8e523cb`. After: auto deploy `off` at 02:44:52Z, auto restart `off`, Health unchanged. Deploy status: on disk `8e523cb` (deployed 01:23:08Z by the auto deploy, `changed_files: []`, a docs only commit, so the code on disk equals the running `d00fa2f`), five backups, `python_ok: true` | Pass: pushes to `dev` no longer reach the instance's disk until the Build A exit deploys `v0.3.0-beta.1` by hand and turns the switch back on | 2026-10-18 | n/a (L26 write) |
| The switch holds | MCP reads after the next green push | `dev-stable` moved to `985d8a4` at 02:53:07Z; auto deploy still `off`; deploy status still `8e523cb` on disk, five backups unchanged | Pass | 2026-10-18 | n/a (read only) |
| The switch held through Build A | MCP reads at the exit | `dev-stable` moved with every green push of Build A (last `a147fec` before the exit); auto deploy still `off` since 02:44:52Z; the disk still held `8e523cb` until the hand deploy below | Pass | 2026-10-18 | n/a (read only) |
| Build A exit deploy by hand (plan 0.1.6, A4.5) | Read before; `shell_command.deploy_device_routines` with `ref: v0.3.0-beta.1` and `return_response`; read after with `shell_command.device_routines_deploy_status` | Before: Health `ok` on `d00fa2f` (running), disk `8e523cb`, auto deploy `off`. Response: `ok: true`, `changed: true`, commit `efbf757` (the `v0.3.0-beta.1` tag, `main`), previous `8e523cb`, 45 changed files, `restart_required: true`, `python_ok: true`, no warnings. After: deploy status names `efbf757` on branch `v0.3.0-beta.1` at 07:31:35Z, five backups (the oldest rotated out); Health still `ok` on `d00fa2f` until the restart | Pass: R1 requested (owner log O15); auto deploy left `off` (decision L58) | 2026-10-18 | n/a (L26 write) |

## Harness rows

Task A4.4: one row per behavior matrix id, per test file group and per acceptance scenario
that runs in the harness. Phase 3 rows (weekly schedules, keep alive, pulse, the late start
window, triggers and conditions, the AI path, the WebSocket API, conflicts, M9, the
settings catalog, G5) are in `phase-3.md`.

### Behavior matrix

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| B01 window on and off the same day | Harness, time travel | `tests/blueprint/test_windows.py::test_b01_window_on_and_off_the_same_day` | Pass | 2026-10-18 | n/a |
| B02 window crossing midnight | Harness, time travel | `tests/blueprint/test_windows.py::test_b02_window_crossing_midnight` | Pass | 2026-10-18 | n/a |
| B03 crossing window with weekdays follows the start day | Harness, time travel | `tests/blueprint/test_windows.py::test_b03_crossing_window_with_weekdays_follows_the_start_day` | Pass | 2026-10-18 | n/a |
| B04 weekends only | Harness, time travel | `tests/blueprint/test_windows.py::test_b04_weekends_only` | Pass | 2026-10-18 | n/a |
| B05 some days | Harness, time travel | `tests/blueprint/test_windows.py::test_b05_some_days` | Pass | 2026-10-18 | n/a |
| B08 one shot start with the docked guard | Harness, time travel | `tests/blueprint/test_windows.py::test_b08_one_shot_start_with_the_docked_guard` | Pass | 2026-10-18 | n/a |
| B09 turn off after a manual on | Harness, time travel | `tests/blueprint/test_durations.py::test_b09_turn_off_after_a_manual_on` | Pass | 2026-10-18 | n/a |
| B10 turn off after cancelled by a manual off | Harness, time travel | `tests/blueprint/test_durations.py::test_b10_turn_off_after_is_cancelled_by_a_manual_off` | Pass | 2026-10-18 | n/a |
| B11 turn off after survives a restart | Harness, time travel | `tests/blueprint/test_durations.py::test_b11_turn_off_after_survives_a_restart` | Pass | 2026-10-18 | n/a |
| B12 turn off after not applied inside an explicit window | Harness, time travel | `tests/blueprint/test_durations.py::test_b12_turn_off_after_is_not_applied_inside_an_explicit_window` | Pass | 2026-10-18 | n/a |
| B13 turn off after applies after an on without an off | Harness, time travel | `tests/blueprint/test_durations.py::test_b13_turn_off_after_applies_after_an_on_without_an_off` | Pass | 2026-10-18 | n/a |
| B18 D27 rejection of both durations | Harness, time travel | `tests/blueprint/test_durations.py::test_b18_both_durations_are_rejected` | Pass | 2026-10-18 | n/a |
| B19 catch up on start inside a window | Harness, time travel | `tests/blueprint/test_windows.py::test_b19_catch_up_on_start_inside_a_window` | Pass | 2026-10-18 | n/a |
| B20 catch up on reconnect | Harness, time travel | `tests/blueprint/test_windows.py::test_b20_catch_up_on_reconnect` | Pass | 2026-10-18 | n/a |
| B23 manual change sets override and suppresses catch up | Harness, time travel | `tests/blueprint/test_override.py::test_b23_manual_change_sets_override_and_suppresses_catch_up` | Pass | 2026-10-18 | n/a |
| B24 a scheduled time clears override | Harness, time travel | `tests/blueprint/test_override.py::test_b24_a_scheduled_time_clears_override` | Pass | 2026-10-18 | n/a |
| B25 a person clears override, catch up runs | Harness, time travel | `tests/blueprint/test_override.py::test_b25_a_person_clears_override_and_catch_up_runs` | Pass | 2026-10-18 | n/a |
| B26 respect manual off sets no override | Harness, time travel | `tests/blueprint/test_override.py::test_b26_respect_manual_off_sets_no_override` | Pass | 2026-10-18 | n/a |
| B27 pause blocks scheduled and countdown actions and fires the event | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b27_pause_blocks_countdown_actions_and_fires_the_event`, `tests/blueprint/test_pause_and_skip.py::test_b27_pause_blocks_scheduled_actions_and_fires_the_event` | Pass | 2026-10-18 | n/a |
| B28 pause pauses and resumes a running countdown | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b28_pause_pauses_and_resumes_a_running_countdown_with_the_time_left` | Pass | 2026-10-18 | n/a |
| B29 pause end catches up (D20) | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b29_pause_end_catches_up` | Pass | 2026-10-18 | n/a |
| B30 resume ends the pause and catches up | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b30_resume_ends_the_pause_and_catches_up` | Pass | 2026-10-18 | n/a |
| B31 skip next on a window start (D18) | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b31_skip_next_on_a_window_start_skips_both_ends` | Pass | 2026-10-18 | n/a |
| B32 skip next on a window end (D19) | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b32_skip_next_on_a_window_end` | Pass | 2026-10-18 | n/a |
| B33 skip next on a running countdown | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b33_skip_next_on_a_running_countdown` | Pass | 2026-10-18 | n/a |
| B34 skip next pressed twice extends | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b34_pressing_skip_next_twice_extends_the_skip` | Pass | 2026-10-18 | n/a |
| B35 manual change while paused, no override (D21) | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b35_manual_change_while_paused_sets_no_override` | Pass | 2026-10-18 | n/a |
| B36 routine off runs nothing, keeps the pause | Harness, time travel | `tests/blueprint/test_pause_and_skip.py::test_b36_routine_off_runs_nothing_and_keeps_the_pause` | Pass | 2026-10-18 | n/a |
| B39 refused actions never fire | Harness, time travel | `tests/blueprint/test_refusals.py::test_b39_control_every_path_calls_an_allowed_on_action`, `tests/blueprint/test_refusals.py::test_b39_refused_actions_never_fire` | Pass | 2026-10-18 | n/a |
| B40 DST spring forward | Harness, time travel | `tests/blueprint/test_windows.py::test_b40_dst_spring_forward_skips_a_time_in_the_missing_hour` | Pass | 2026-10-18 | n/a |
| B41 DST fall back | Harness, time travel | `tests/blueprint/test_windows.py::test_b41_dst_fall_back_runs_a_repeated_time_twice_as_a_no_op` | Pass | 2026-10-18 | n/a |
| B42 a queued burst in order | Harness, time travel | `tests/blueprint/test_windows.py::test_b42_a_queued_burst_is_processed_in_order` | Pass | 2026-10-18 | n/a |
| B43 integration disabled, the routine still runs | Harness, time travel | `tests/blueprint/test_without_integration.py::test_b43_integration_disabled_the_routine_still_runs` | Pass | 2026-10-18 | n/a |
| B44 attribution: time triggered automation change is not manual | Harness, time travel | `tests/integration/test_attribution.py::test_b44_time_triggered_automation_change_is_automation` | Pass | 2026-10-18 | n/a |
| B45 attribution: wall switch change is manual | Harness, time travel | `tests/integration/test_attribution.py::test_b45_wall_switch_change_is_device` | Pass | 2026-10-18 | n/a |
| B46 attribution: app change is manual | Harness, time travel | `tests/integration/test_attribution.py::test_b46_app_change_is_user` | Pass | 2026-10-18 | n/a |

### Test files

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Compiler, markers, skip targets (lane 1) | Harness: `tests/unit/test_compiler.py`, `test_markers.py`, `test_nextrun.py`, `test_sentence.py` | 86, 30, 60 and 71 tests: both round trips (hypothesis), refusals never compiled, every `validate` rejection, D18 and D19 skip targets, the 40 character state cap | Pass | 2026-10-18 | n/a |
| Blueprint schema (lane 2) | Harness: `tests/blueprint/test_schema.py` | 15 tests: the 29 inputs in order, no `source_url` (L24), `min_version` 2026.10.2, aliases everywhere, queued 10, no `schedule.block_started` (A6), the caught up twin (L20), `not_paused` the only template (L22) | Pass | 2026-10-18 | n/a |
| Adapter write path (lane 3) | Harness: `tests/integration/test_adapter.py` | 42 tests: create, update, delete with a run in flight elsewhere; unowned refused; other entries kept; one retry then `write_conflict` (L37); blueprint install; system user; helpers with chosen ids and the label (L36); restore state; release and take control (L51) | Pass | 2026-10-18 | n/a |
| Attribution (lane 4) | Harness: `tests/integration/test_attribution.py` | 34 tests: the V3 replay, map cap and TTL, startup grace, override set and cleared, none while paused (D21) (L35) | Pass | 2026-10-18 | n/a |
| Manager, sync back, reconcile (lane 5, A4.0) | Harness: `tests/integration/test_manager.py`, `test_sync_back.py`, `test_reconcile.py` | 52, 17 and 22 tests: every PRD 3.1 row, the write algorithm, debounce, label deletion opts nobody out, same named devices, take control, git restore, missing helpers, load failures, missing target across a restart (L44, L57) | Pass | 2026-10-18 | n/a |
| Store, migrations, maintenance (lane 6, A4.0) | Harness: `tests/integration/test_store.py`, `test_migration.py`, `test_maintenance.py` | 20, 15 and 28 tests: Store 1.2 round trip and migrations from 0 and 1.1, newer versions refused, options version 2, the schema migration from a fake schema 0, every maintenance action idempotent with dry run, translated failures (L42, L57) | Pass | 2026-10-18 | n/a |
| Schedule summary with routines (lane 7) | Harness: `tests/integration/test_summary.py` | 46 tests: routine items first, Skipped, Paused until and Routine off states, refresh of one device, detached routines, midnight rewording (L43, L57) | Pass | 2026-10-18 | n/a |
| Device page controls (lane 8) | Harness: `tests/integration/test_platforms.py` | 67 tests: the entity set per profile, categories and enabled defaults, every write through the manager, availability reasons, restore, the hub Clean up now button, `PARALLEL_UPDATES` (L52, L57) | Pass | 2026-10-18 | n/a |
| Actions (lane 9) | Harness: `tests/integration/test_services.py` | 23 tests: six actions with device, area, floor, label and entity targets, the ignored list (S13), `no_routine_targets`, responses, translations and icons (L46) | Pass | 2026-10-18 | n/a |
| Removal and the devices picker (lane 10) | Harness: `tests/integration/test_config_flow.py` | 23 tests: suggestions, the devices picker, keep and delete removal (S8), the system user removed (L51) | Pass | 2026-10-18 | n/a |
| Repairs catalog (lane 11) | Harness: `tests/integration/test_repairs.py`, `test_repairs_sync.py` | 35 and 5 tests: every catalog issue raised and cleared, every fix flow one step, the Problem sensor (L41, L48) | Pass | 2026-10-18 | n/a |
| Health and diagnostics (lane 15) | Harness: `tests/integration/test_health.py`, `test_diagnostics.py` | 34 and 10 tests: the degraded and error rules, every new attribute, the deploy contract unchanged, the Store as counts and records as redacted shapes (L50) | Pass | 2026-10-18 | n/a |
| Contracts (A4.1) | Harness: `tests/integration/test_contracts.py` | 111 tests: `compile()` validates against the installed blueprint for 18 profile cases (hypothesis), the hand written mirror equals `compile()`, P16 for 14 surface modules, the PRD 12 round trip through the manager and through the summary alone (L56) | Pass | 2026-10-18 | n/a |
| 30 day simulation, G8 (A4.2) | Harness: `tests/integration/test_thirty_days.py` | Three routines over 2026-11-02 to 2026-12-02: 214 state changes checked to the second, 274 sentence checks, renames, a target rename mid countdown, a restore from a backup, an update over a fake schema 0, a device offline and removed with cleanup, two cold starts; no issue raised, Health ok throughout, the Store rebuilt equals the Store kept (L56) | Pass | 2026-10-18 | n/a |

### Acceptance scenarios in the harness (PRD 13.4)

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| S6 form edit, refusal and restore (harness) | Harness | `test_sync_back.py::test_a_form_edit_with_a_hash_the_manager_did_not_write_updates_the_entities`, `::test_a_refused_action_does_the_same_and_correcting_the_form_brings_it_back`, `test_repairs.py::test_the_invalid_inputs_fix_restores_the_last_valid_inputs` | Pass | 2026-10-18 | n/a |
| S7 take control and the lookalike (harness) | Harness | `test_sync_back.py::test_take_control_makes_the_routine_detached_and_raises_detached_routine`, `test_manager.py::test_a_lookalike_automation_is_never_written_and_never_listed`, `test_repairs.py::test_the_detached_fix_creates_a_new_routine_and_never_touches_the_old_one` | Pass | 2026-10-18 | n/a |
| S8 removal with keep (harness) | Harness | `test_config_flow.py::test_removing_with_keep_leaves_standalone_automations_that_still_run` | Pass | 2026-10-18 | n/a |
| S11 skip next (harness) | Harness | `tests/blueprint/test_pause_and_skip.py::test_b31_skip_next_on_a_window_start_skips_both_ends`, `test_manager.py::test_skip_next_sets_paused_until_from_skip_target`, `test_triggers_conditions.py::test_every_trigger_fires_for_each_target_kind` | Pass | 2026-10-18 | n/a |
| S12 pause across a restart (harness half) | Harness | `test_thirty_days.py`, day 5: a 2 hour pause on an area, the 17:00 start skipped with the event, a cold start inside the pause, catch up at 18:30 (D20) | Pass | 2026-10-18 | n/a |
| S13 a label with a plain device (harness) | Harness | `test_services.py::test_skip_next_on_a_label_skips_the_routine_and_lists_the_plain_device` | Pass | 2026-10-18 | n/a |
| S3 missed on time caught up (restart half) | Harness | `test_thirty_days.py`, day 5: the 17:15 block start missed during the downtime, on at the start; `tests/blueprint/test_windows.py::test_b19_catch_up_on_start_inside_a_window` | Pass | 2026-10-18 | n/a |
| S4 manual on across a restart (restart half) | Harness | `test_thirty_days.py`, day 25: a user's on in the off period survives a cold start with Manual override on and `last_change_source: user`, cleared at 17:00; `tests/blueprint/test_override.py::test_b23_manual_change_sets_override_and_suppresses_catch_up` | Pass | 2026-10-18 | n/a |
| S5 countdown across a restart (restart half) | Harness | `test_thirty_days.py`, day 25: Turn off after 45 across a cold start, off on time; `tests/blueprint/test_durations.py::test_b11_turn_off_after_survives_a_restart` | Pass | 2026-10-18 | n/a |

### Whole suite at the harness exit (A4.4)

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Whole suite | `pytest -m "not live" --cov` on `dev` | 1831 passed, 6 skipped (the live suite and Stage 0 probes that need a live instance), 4 deselected (`live`), no xfail; total coverage 99.87 percent, every integration module at 100 percent line and branch; 1 minute 46 seconds | Pass | 2026-10-18 | n/a |
| Static gates and CI | `ruff check`, `ruff format --check`, `mypy --strict`, style and privacy checks locally; CI (lint, typecheck, style, privacy, test pinned and latest, hassfest, HACS, deploy tool parity) | Every local gate clean; CI green on every job, hassfest included, from `b277a3d` on; the exit commit's own CI run is the one the `main` fast forward waits for. A wall clock dependent Stage 0 test that failed near local midnight now runs at a fixed instant (L57); six repeated runs of the two other tests seen failing once under parallel load were green | Pass | 2026-10-18 | n/a |

## Restart R1 bundle (plan Section 5.2, template 9.6)

| Field | Content |
| --- | --- |
| Restart | R1, the owner's, 2026-10-18 at about 15:16Z (owner log O15, decision L59) |
| Deployed before | `efbf757` (`v0.3.0-beta.1`) on disk since 07:31:35Z, from `shell_command.device_routines_deploy_status` (the Build A exit deploy row above); Health read `d00fa2f` running until the restart |
| Staged | Nothing, as plan 5.2 says for R1 (first load: no routine exists before it). The plan 5.1 step 2 baseline was not read before the restart, because the restart happened before this session started; it is read after instead: the sandbox plug `on` since 15:16:03Z, turned on by its hand written automation's start reconcile (automation `on`, last triggered 15:16:21Z) |
| Running after | Health `ok`, `commit` `efbf757` (branch `v0.3.0-beta.1`), version 0.3.0, `blueprint_schema: 1`, `blueprint_status: ok`, `owned_count: 0`, `loaded_count: 0`, `issues: []`, `last_reconcile` 15:16:21Z, Home Assistant 2026.10.2. Time to `ok`: within the start (the first reconcile ran at 15:16:21Z, 18 seconds after the plug came back on); not measured to the second, since no session was reading during the restart |
| Read after | No staged scenario. The Section 5.3 rows follow |

## Live rows

Filled after restart R1 (plan Section 5.3). Phase 3 rows of the same section (the
WebSocket API, keep alive, pulse, weekly schedules, the editor pickers) are in
`phase-3.md`.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| 5.3 step 1: Health, blueprint, label, category, Repairs, Schedule sensors | MCP reads: a template over Health, the hub entities and the Schedule sensors; the label and automation category registries; the blueprint list; `repairs/list_issues`; `shell_command.device_routines_deploy_status`; the system log filtered on the integration | Health as in the R1 bundle above. Deploy status: `efbf757` on `v0.3.0-beta.1` since 07:31:35Z, five backups, `python_ok: true`, `hacs_managed: false`. The `Routines` label exists (icon `mdi:calendar-clock`, on no device or entity yet) and exactly one automation category, `Device Routines` (same icon). The blueprint `device_routines/device_routine.yaml` is installed, author Device Routines, no `source_url` (L24). No Repairs issue of the integration (the other domains' issues predate the restart and are unrelated). Hub entities: Problem `off`, Routines `0`, Clean up now present. 10 Schedule sensors, the same number as the Phase 1 record, none unavailable. No system log entry of the integration. Auto deploy and auto restart both `off` (L58). `pytest -m live` not run: `local/live.env` does not exist yet (O2), so these MCP reads stand in for it | Pass | 2026-10-18 | n/a (read only) |
| 5.3 step 3: the sandbox plug's hand written automation off | Read before over MCP; `automation.turn_off`; read after | Read before: the plug `on` since 15:16:03Z, the hand automation `on`, the plug's Schedule sensor reading the hand automation's next off (four parser items, no conflict). The write was refused by Claude Code's auto mode classifier in this session ("Modify Shared Resources"), and so was a plain state read right after it; nothing was written, so the instance is unchanged | Not run: waits for the owner to allow the live session's Home Assistant calls (owner log O17) | 2026-10-18 | |
| 5.3 steps 4 to 8 and 13: S2, S6, S7, S11, S13, end state | Live writes on the sandbox device (L26) | None yet | Not run: wait on step 3 (O17). The harness rows above stand meanwhile | 2026-10-18 | |
| 5.3 step 9: S1, a hand written weekday automation's next start | MCP read (template, before the refusal) | The Schedule sensor of a device that a hand written weekday automation starts read `Start Mon <time>` on a Sunday, which is that automation's next start. Its attributes (`kind: automation`) were not read before the refusal | Partly: the sentence passes; the attribute read waits on O17 | 2026-10-18 | n/a (read only) |
