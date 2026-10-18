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

Filled after restart R1 (plan Section 5.3).

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
