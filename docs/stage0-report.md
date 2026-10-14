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
