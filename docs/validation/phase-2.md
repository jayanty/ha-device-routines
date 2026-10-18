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

## Harness rows

Filled at task A4.4: one row per behavior matrix id, per integration test file and per
acceptance scenario that runs in the harness.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |

## Live rows

Filled after restart R1 (plan Section 5.3).

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
