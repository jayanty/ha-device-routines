# Phase 3 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 4 (Build A, Phase 3 rows) and
Section 5 (live validation A), in the format of template 9.1. Evidence is quoted as the
tools print it, without instance names. Phase 2 rows and the Build A deploy stance are in
`phase-2.md`.

## Harness rows

### Behavior matrix

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| B06 weekly schedule blocks | Harness, time travel | `tests/blueprint/test_windows.py::test_b06_weekly_schedule_blocks` | Pass | 2026-10-18 | n/a |
| B07 adjacent blocks at midnight, no blip | Harness, time travel | `tests/blueprint/test_windows.py::test_b07_adjacent_blocks_at_midnight_produce_no_blip` | Pass | 2026-10-18 | n/a |
| B14 keep alive after a device originated off | Harness, time travel | `tests/blueprint/test_durations.py::test_b14_turn_back_on_after_a_device_originated_off` | Pass | 2026-10-18 | n/a |
| B15 keep alive never during a scheduled off | Harness, time travel | `tests/blueprint/test_durations.py::test_b15_turn_back_on_after_never_during_a_scheduled_off` | Pass | 2026-10-18 | n/a |
| B16 keep alive cancelled by an on | Harness, time travel | `tests/blueprint/test_durations.py::test_b16_turn_back_on_after_is_cancelled_by_an_on` | Pass | 2026-10-18 | n/a |
| B17 keep alive survives a restart | Harness, time travel | `tests/blueprint/test_durations.py::test_b17_turn_back_on_after_survives_a_restart` | Pass | 2026-10-18 | n/a |
| B21 one shot late start inside the window | Harness, time travel | `tests/blueprint/test_windows.py::test_b21_one_shot_late_start_inside_the_window` | Pass | 2026-10-18 | n/a |
| B22 one shot outside the window waits; a zero window means no late start | Harness, time travel | `tests/blueprint/test_windows.py::test_b22_a_zero_late_start_window_means_no_late_start`, `tests/blueprint/test_windows.py::test_b22_one_shot_outside_the_window_waits` | Pass | 2026-10-18 | n/a |
| B37 pulse | Harness, time travel | `tests/blueprint/test_pulse.py::test_b37_no_pulse_unless_steady`, `tests/blueprint/test_pulse.py::test_b37_pulse` | Pass | 2026-10-18 | n/a |
| B38 pulse repaired by catch up after a restart | Harness, time travel | `tests/blueprint/test_pulse.py::test_b38_pulse_interrupted_by_a_restart_is_repaired_by_catch_up` | Pass | 2026-10-18 | n/a |

### Test files

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Weekly schedules (lane 14, A4.0) | Harness: `tests/integration/test_weekly_schedule.py` | 23 tests: the helper created, labeled, linked and kept, the time controls unavailable, `schedule_blocks_needed` cleared by `next_event`, Skip next over blocks, kept helpers found after a rename and a restart (L53, L57) | Pass | 2026-10-18 | n/a |
| AI summary path (lane 14) | Harness: `tests/integration/test_ai_path.py` | 27 tests: off by default, only unread hand written automations sent as blocks with entity ids, one at a time, the token bucket, the cache, nothing in the first five minutes, the `(AI)` suffix (L53) | Pass | 2026-10-18 | n/a |
| Hub Routines sensor (lane 14) | Harness: `tests/integration/test_hub_routines.py` | 5 tests: every routine listed with device, area, summary, next action, status and automation; the count of active routines | Pass | 2026-10-18 | n/a |
| Triggers and conditions, FR-R17 (lane 13) | Harness: `tests/integration/test_triggers_conditions.py` | 19 tests: three triggers and two conditions with device, area, floor, label and entity targets, behavior each, first, all and any, all, descriptions for the editor's pickers, linked records (L47, L57) | Pass | 2026-10-18 | n/a |
| WebSocket API (lane 12) | Harness: `tests/integration/test_websocket_api.py`, `test_summary_day.py` | 68 and 6 tests: every TECH_SPEC 4.7 command equal to the manager's own result, admin for writes, subscriptions across reloads, ISO datetimes, the day's schedule (L49) | Pass | 2026-10-18 | n/a |
| Conflicts to Repairs (lane 11) | Harness: `tests/integration/test_repairs.py` | the `conflict` tests: only a routine against another automation in the same minute, only while Raise conflict repairs is on, cleared when the collision ends (L48) | Pass | 2026-10-18 | n/a |
| Settings catalog (lanes 6, 10) | Harness: `tests/integration/test_config_flow.py`, `tests/unit/test_domains_settings_conflicts.py` | every PRD 10.4 setting on the settings page with its default and translated validation errors; options version 2 migration (L42, L51) | Pass | 2026-10-18 | n/a |
| M9 area follows (lane 5) | Harness: `tests/integration/test_reconcile.py::test_the_area_follows_the_device_when_assign_area_is_on` | the automation's area follows the device while Assign area is on | Pass | 2026-10-18 | n/a |
| G5 golden corpus (A4.3) | Harness: `tests/golden/test_lines.py`, `test_corpus.py`, `tests/unit/test_parser.py` | 51 of 56 items parsed (91.1 percent), zero wrong lines, every changed line reviewed; 175 parser unit tests (L55) | Pass | 2026-10-18 | n/a |

## Live rows

Filled after restart R1 (plan Section 5.3). Phase 2 rows of the same section and the R1
restart bundle are in `phase-2.md`.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| 5.3 step 2: the read only WebSocket commands | MCP `ha_call_service` with `ws_command` | `device_routines/routines/list`: `routines: []`. `device_routines/settings/get`: every PRD 10.4 default (scope `all`, time format `auto`, catch up and respect manual on, late start window 15, cleanup after 30 days, assign area on, removal `keep`, no AI Task entity, 20 AI calls per hour, conversion offers and conflict repairs on). `device_routines/devices/opt` `list`: 120 devices, each with its controllable targets and no configuration or diagnostic entity. `devices/opt` `suggest`: 3 devices, exactly the devices that hand written time triggered automations drive, the sandbox plug's device among them. `device_routines/schedule/today`: the day's 4 planned actions, all `kind: automation`, sorted by time, earlier ones of the day included as planned, no conflict | Pass | 2026-10-18 | n/a (read only) |
| 5.3 step 10a: keep alive, FR-R4 (compressed) | Turn on at moved three minutes ahead so an on period began inside the session; `routines/set` Turn back on after 2 (Turn off after 0, D27); `switch.turn_off` on the plug over MCP; reads and traces; Turn back on after back to 0 | The scheduled on at 17:25:00Z turned the plug on and the routine's own `timer.routine_<slug>` helper existed. The user off at 17:25:28Z: Manual override `on`, `last_change_source: user`, the timer `active` for 0:02:00. At 17:27:28Z the timer finished and the routine turned the plug back on in the same second (`last_change_source: automation`); the trace ran the Turn back on after branch. The override stayed on until the next scheduled time cleared it (phase-2 record). Reset to 0: the entry back to the sentinel timer, the helper kept for the cleanup period | Pass | 2026-10-18 | Jayant (in chat: live reads and writes on the sandbox plug, L26) |
| 5.3 step 10b: pulse, FR-R8 | The blueprint form path: the entry written over the config endpoint with `pulse_enabled`, a pulse three minutes ahead, 2 minutes, steady guard 1; reads of the view and the plug; `routines/set` `pulse: null` to clear | The form edit synced back within a second: `pulse: {at, minutes: 2, min_steady_min: 1}`, sentence `Toggle at <time>`. At the pulse time (17:31:00Z) the routine turned the steady plug off, held its delay (`current: 1`), and turned it on at 17:33:00Z, both with `last_change_source: automation`. Cleared: the entry back to `pulse_enabled: false` | Pass | 2026-10-18 | Jayant (in chat: live reads and writes on the sandbox plug, L26) |
| 5.3 step 11: weekly schedule, FR-R2 | The device page Days select to Weekly schedule, then back to Every day; reads of the helper, its labels and device, the time controls, Health and the view | Weekly schedule: `schedule.routine_<slug>` created empty (`off`), labeled `Routines`, on no device (L36); Turn on at and Turn off at `unavailable` with reason `weekly_schedule`; the times dropped as the manager documents; no issue raised; the plug untouched. Every day again: the helper kept and unlinked (`schedule_entity: null`), the cleanup period governs it; the times stayed dropped and were set again for the end state | Pass | 2026-10-18 | Jayant (in chat: live reads and writes on the sandbox plug, L26) |
| 5.3 step 12: the editor's trigger and condition pickers | Owner look (O4) | Asked in chat at the end of this session; the live half of the trigger ran in S11 (phase-2 record) | Waiting for the owner's look (O4) | 2026-10-18 | |
