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
