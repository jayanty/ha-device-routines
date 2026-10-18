# Phase 4 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 6 (Build B: FR-R9, FR-R10,
FR-M1, the console, publication) and Section 6.3 (live validation B), in the format of
template 9.1. Evidence is quoted as the tools print it, without instance names. Test
counts are those of the commit that tags `v1.0.0-beta.1`.

## Harness rows

### Behavior matrix

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| B47 sun window on and off | Harness, time travel and cold starts | `tests/blueprint/test_sun.py::test_b47_sun_window_on_and_off`, `test_b47_catch_up_on_start_follows_the_sun_window` (four cold starts) | Pass | 2026-10-18 | n/a |
| B48 sunset to sunrise across midnight | Harness, time travel and cold starts | `tests/blueprint/test_sun.py::test_b48_sunset_to_sunrise_across_midnight`, `test_b48_catch_up_across_midnight_follows_the_start_day`, `test_b48_one_shot_sun_start_late_window`, `test_b48_a_zero_late_start_window_means_no_late_sun_start` | Pass | 2026-10-18 | n/a |
| B49 Only when blocks a scheduled action and fires nothing | Harness, time travel | `tests/blueprint/test_only_when.py::test_b49_only_when_blocks_a_scheduled_action_and_fires_nothing` (a time start and a sunset start) | Pass | 2026-10-18 | n/a |
| B50 schema 1 to 2 leaves every routine running | Harness, blueprint swap and reloads | `tests/blueprint/test_schema_migration.py::test_b50_schema_1_routine_keeps_running_on_schema_2` (two routines; no state change at either reload, the next actions run), the schema 1 file pinned by its sha256 | Pass | 2026-10-18 | n/a |
| Skip next on a sun start | Harness, time travel | `tests/blueprint/test_sun.py::test_skip_next_on_a_sun_start_fires_the_skipped_event` | Pass | 2026-10-18 | n/a |

### Test files

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Sun bounds in the pure core (lane 16) | Harness: `tests/unit/test_compiler.py`, `test_nextrun.py`, `test_sentence.py` | Round trips with sun bounds drawn, the 38 inputs of schema 2, nominal ordering, the offset text, `expected_state` and the occurrences of sun windows on the 2026 DST nights, the sun routine sentence under the 40 character cap (L60, L64) | Pass | 2026-10-18 | n/a |
| Schema 1 read rule (lane 16) | Harness: `tests/integration/test_migration.py` | 120 recorded schema 1 cases read unchanged through `DECOMPILERS[1]`, schema 2 keys refused (L60) | Pass | 2026-10-18 | n/a |
| The blueprint against `nextrun` | Harness: `tests/integration/test_contracts.py::test_expected_on_equals_expected_state` | The shipped blueprint's rendered `expected_on` equals `expected_state` over drawn settings with sun bounds and instants across 2026, never on a sun bound; midnight ends pinned (L64, L69) | Pass | 2026-10-18 | n/a |
| Sun bounds on the device page (lane 19) | Harness: `tests/integration/test_sun_routines.py` | 11 tests: the companion controls disabled by default per profile, schema 2 inputs written, `sun_bound` and `time_bound`, catch up and override over a sun window, Skip next pairing, the next action and sentence, Only when lines (L69) | Pass | 2026-10-18 | n/a |
| The schema 2 first load (lane 19) | Harness: `tests/integration/test_schema_2_first_load.py` | Every schema 1 routine rewritten with `previous_inputs` kept and no device state change, Health `blueprint_schema: 2`; a failed migration raises `automation_load_failed` and its fix retries (L69) | Pass | 2026-10-18 | n/a |
| Conversion offers (lane 20) | Harness: `tests/integration/test_conversion_offers.py`, `tests/unit/test_conversion.py` | 19 and 19 tests: exact matches offered once, no offer with a routine, a disabled automation or the setting off, both sentences in the issue, confirming creates the routine and turns off and labels the original without editing it, the undo, every refusal leaves the original untouched, an offer is not a problem (L61, L65, L67) | Pass | 2026-10-18 | n/a |
| Golden corpus offers (lane 20) | Harness: `tests/golden/test_offers.py` | 4 of 51 fixtures offered (`automation_16`, `automation_23`, `synthetic_01`, `synthetic_03`), every other fixture that acts on a device named with its reason, partial matches included (L67) | Pass | 2026-10-18 | n/a |
| The console's views (lanes 18, 21) | vitest: `frontend/test/*.test.ts` | 104 tests over the payloads recorded from `docs/api.md`: the three views, every action payload, translated refusals, subscriptions, the L63 fields, the conversion section (L62, L63, L68) | Pass | 2026-10-18 | n/a |
| The console in Home Assistant (lane 21) | Harness: `tests/integration/test_panel.py` | The panel admin only and removed on unload, kept across reloads; the bundle served with the version query; every request example of `docs/api.md` answered with its shape by the real WebSocket API (L68) | Pass | 2026-10-18 | n/a |
| Wave B2 carry overs (lane 22) | Harness: `tests/unit/test_domains_settings_conflicts.py`, `tests/integration/test_summary.py`, `test_websocket_api.py`, `test_sun_routines.py` | `test_a_sun_window_routine_gets_window_conflicts` (unit and summary), `test_a_conflict_a_change_creates_is_answered_at_once` (`routines/set` and `schedule/today` before the write), `test_a_sun_instant_reads_to_the_minute`, `test_a_hand_written_sun_trigger_reads_to_the_minute` (L69, L72) | Pass | 2026-10-18 | n/a |
| Live finding F1: a delete in the editor (lane 22) | Harness: `tests/integration/test_sync_back.py`, through the real config view's DELETE | `test_an_owned_routine_deleted_in_the_editor_resets_at_once`, `test_a_detached_routine_deleted_in_the_editor_clears_its_issue`, `test_deleting_another_automation_in_the_editor_leaves_the_routine_alone`, `test_a_sync_during_the_managers_own_delete_leaves_the_routine_to_it`; each failed on the 0.3.0 code (L71, L72) | Pass | 2026-10-18 | n/a |
| Live finding F2: every automation off (lane 22) | Harness: `tests/integration/test_summary.py`, `tests/unit/test_sentence.py` | `test_a_device_whose_automations_are_all_off_reads_automations_off`, `test_a_device_whose_automations_are_all_off_reads_automation_off` (L71, L72) | Pass | 2026-10-18 | n/a |
| Brand assets (lane 23) | Harness: `tests/test_repository.py`, `tests/tools/test_make_brand.py` | The drawn set exactly, RGBA with transparent corners, trimmed, icons 256 and 512 square, logos landscape within the brands limits, the brands layout equal to `brand/`, `tools/make_brand.py` reproducing the files (L72) | Pass | 2026-10-18 | n/a |
| Brand images in the integration (L78) | Harness: `tests/test_repository.py`, `tests/tools/test_make_brand.py`; the release workflow's zip command run locally | `test_the_integrations_brand_folder_mirrors_brand`, `test_the_hacs_brands_check_finds_the_icon_where_it_looks`, `test_the_hacs_job_ignores_no_check`, `test_the_release_zip_carries_the_brand_folder`; `tools/make_brand.py --check` clean; the local zip lists the six images under `brand/` | Pass | 2026-10-18 | n/a |
| The `frontend` check | CI on Linux | `frontend` job green on `fba3eed`: typecheck, vitest, build, the committed bundle equal to the fresh build; a required check of `main` since 2026-10-18 (L70) | Pass | 2026-10-18 | n/a |

## Build B exit and the R2 restart bundle

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Exit CI | GitHub Actions on `db7fa10` | every job green, `frontend` included; `main` fast forwarded `efbf757..db7fa10` | Pass | 2026-10-18 | n/a |
| Pre release | `release.yml` on the tag `v1.0.0-beta.1` | a pre release with `device_routines.zip` | Pass | 2026-10-18 | n/a |
| Read before the deploy | `shell_command.device_routines_deploy_status` over MCP | deployed `efbf757` (`v0.3.0-beta.1`, 07:31:35Z), `hacs_managed: false`, `python_ok: true` | Pass | 2026-10-18 | L26 |
| Hand deploy | `shell_command.deploy_device_routines` with `ref: v1.0.0-beta.1` | `ok: true`, `changed: true`, commit `db7fa10`, previous `efbf757`, 27 changed files, `restart_required: true`, no warnings | Pass | 2026-10-18 | L26 |
| Read after the deploy | `device_routines_deploy_status`, Health, the auto deploy switch | deployed `db7fa10` at 18:02:19Z with a backup of `efbf757`; Health `ok` still running `efbf757` (version 0.3.0, blueprint schema 1, one owned routine); auto deploy `off` | Pass | 2026-10-18 | L26 |
| Exit CI for `v1.0.0-beta.2` | GitHub Actions on `01ca0b3` (`v1.0.0-beta.1` plus the L73 race fix) | every job green; `main` fast forwarded `db7fa10..01ca0b3` | Pass | 2026-10-18 | n/a |
| Pre release `v1.0.0-beta.2` | `release.yml` on the tag | a pre release built | Pass | 2026-10-18 | n/a |
| Read before the second deploy | `device_routines_deploy_status` over MCP | deployed `db7fa10` (`v1.0.0-beta.1`, 18:02:19Z); Health running `efbf757` | Pass | 2026-10-18 | L26 |
| Hand deploy of `v1.0.0-beta.2` | `shell_command.deploy_device_routines` with `ref: v1.0.0-beta.2`, on the owner's instruction so R2 loads the fix | `ok: true`, `changed: true`, commit `01ca0b3`, previous `db7fa10`, changed files `manager.py` only, `restart_required: true`, no warnings | Pass | 2026-10-18 | Jayant |
| Read after the second deploy | `device_routines_deploy_status`, Health, the auto deploy switch | deployed `01ca0b3` at 19:36:49Z with a backup of `db7fa10`; Health `ok` still running `efbf757` (version 0.3.0); auto deploy `off` | Pass | 2026-10-18 | L26 |
| R2 requested | Owner log O16 | the restart waits for the owner, after the live session stages the scenario of the hour | Pending | 2026-10-18 | Jayant |
| The live suite after R2 (F5, F6 fixed, L76) | `.venv/bin/python -m pytest -m live` from the development clone, read only, with the Home Assistant test plugin loaded | 4 passed: `test_health_runs_the_deployed_commit` (Health on `01ca0b3`, the commit of `v1.0.0-beta.2`, version 1.0.0), `test_schedule_sensors_exist_with_valid_states`, `test_no_open_issue_from_this_integration`, `test_share_of_unparsed_lines_is_reported` | Pass | 2026-10-18 | L26 |

## Live rows

Filled after restart R2 (plan Section 6.3).
