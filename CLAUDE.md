# CLAUDE.md: Device Routines

Operating manual for every Claude Code session in this repository. Read this first, then
`docs/PRD.md` (behavior and the decision register), `docs/TECH_SPEC.md` (design),
`docs/IMPLEMENTATION_PLAN.md` (order, validation and rules of engagement) and, when it
exists next to this file, `CLAUDE.local.md` (private instance context, gitignored, never
committed, quoted or copied). `docs/decisions-log.md` holds every choice the PRD and the
spec do not cover; `docs/stage0-report.md` holds what Stage 0 validated.

Style rule for everything generated here (code, comments, docs, UI strings, commit
messages): never use the em dash character. Use a hyphen, a colon or a new sentence.

## 1. What this is

`device_routines` is a public, HACS ready Home Assistant custom integration. It adds start
and stop times, run timers and a plain language Schedule sentence to every device page,
backed by real, clearly marked automations built from a blueprint it ships. Home Assistant
runs the routines; the integration configures them and reads every automation to write
the summaries. The PRD's Section 1 says why, Section 14 lists the decisions.

Delivery: Phase 0 (repository, pipeline, skeleton), Stage 0 (validation probes), Phase 1
(the summary, released as v0.1.0), then two builds (decision L32): Build A is Phases 2 and
3 together (routines, P1 features and the WebSocket API) with one restart, Build B is
Phase 4 (console and publication) with a second restart. The plan's Section 0.1 is the
operating model (parallel lanes, restart bundles, the owner log). The Status line at the
top of `docs/IMPLEMENTATION_PLAN.md` says where we are; the plan's Section 8.3 is the
prompt for every later session.

## 2. Rules that override everything else

1. Never restart Home Assistant. Never call `ha_restart` or `homeassistant.restart`, and
   never reload the config entry as a substitute. Say restart needed and stop. Only the
   opt in automation of the development package may restart, and only once the owner
   turns it on.
2. Read only probes and, since 2026-10-17 (decision L26), write probes and live write
   scenarios against the live instance are pre approved. Every write still needs a read
   before it and a read after it proving the state was restored or is the intended end
   state. Restarts (rule 1) and steps only the owner can take (copying files into the
   config directory, operating devices, looking at the UI) still need the owner.
3. Nothing from `CLAUDE.local.md`, `local/` or the live instance goes into a commit,
   fixture, test, doc, issue, pull request or commit message: no entity ids, device,
   area, floor or person names, automation text, hosts, addresses or tokens. The pre
   commit privacy check must pass; never bypass hooks.
4. Proceed on the PRD decision defaults without asking. Record every choice the PRD and
   the spec do not cover in `docs/decisions-log.md` (template in the plan, Section 9.4).
   Anything that needs the owner goes to `docs/owner-log.md` with the default taken
   meanwhile (plan Section 0.1.4); ask in chat only when a default would be unsafe. Owner
   items never stop the work.
5. Work on `dev`. Conventional commits. Push when the local gates pass. Merge `dev` into
   `main` only at a build exit with green CI, as a fast forward (no merge commits). One
   build at a time; inside a build, lanes run in parallel against the interface contracts
   the plan pins (Section 4.2), each in its own worktree and branch (Section 0.1.2).
6. Tests ship in the same commit as the code they cover. Coverage never drops below 95
   percent. `ruff` (every rule) and `mypy --strict` are clean before every commit. Every
   user facing string has a translation key. `CHANGELOG.md` stays current under
   Unreleased.
7. When a probe or a test contradicts the PRD or the spec: stop the task, write the
   finding in the Stage 0 report or the decisions log, propose the smallest design change,
   and continue with it unless it touches a hard constraint (PRD Section 3), in which case
   ask.
8. End every working session with the session report of the plan's Section 9.3 in chat
   and update the Status line of `docs/IMPLEMENTATION_PLAN.md` in every commit that
   completes a task.
9. Harness first, one restart per build (plan rules 12 and 13): every behavior is proven
   in the harness before it is deployed; the instance's auto deploy switch is off while a
   build is open; the finished build is deployed by hand from its tag; scenarios that need
   a restart are staged before a restart that happens anyway and never get their own.

## 3. Architecture invariants

- Pure modules (`models`, `domains`, `compiler`, `markers`, `parser`, `parser_grammar`,
  `nextrun`, `conflicts`, `sentence`, `settings`) import only the standard library and
  each other. `tests/test_repository.py` parses the imports and fails otherwise.
- Only `ha_adapter.py` touches Home Assistant internals; everything else uses the public
  core, helpers and its own platform's base classes. Same test.
- Behavior lives in `manager.py`, `summary.py`, `attribution.py`, `settings.py` and
  `maintenance.py` (PRD P16). Platforms, actions, triggers, conditions, Repairs flows and
  WebSocket commands are thin callers. A rule inside a platform file is a defect.
- The integration writes only to automations that carry markers M1 and M2 (PRD Section
  8), and the adapter refuses anything else whatever the caller.
- Refused actions (PRD 5.4) are enforced in the compiler, on sync back and in the
  blueprint guards. Adding or removing one needs a decision register entry.
- Schemas are written with `probatio` (`import probatio as vol`); core 2026.10 validates
  with it and only aliases `voluptuous`. Device registry lookups carry the config entry
  id (decisions L9 and L10).
- Storage schema changes need a migration and a test. `custom_components` is a namespace
  package (no `__init__.py`).

## 4. Commands

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg

.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest -m "not live" --cov
.venv/bin/python -m pytest -m live        # read only, needs local/live.env

.venv/bin/python -m tools.make_denylist   # after any registry capture
.venv/bin/python -m tools.privacy_check --staged
.venv/bin/python -m tools.anonymize --output tests/fixtures/<dir> local/captures/<dir>
.venv/bin/python -m tools.style_check
```

The hooks run ruff, mypy on the staged files, the style check and the privacy check on
the staged content and the commit message. A clone that holds `CLAUDE.local.md` must also
hold `local/denylist.txt`, or the privacy check refuses to run.

## 5. The deploy loop: Home Assistant pulls, nobody copies

1. Local gates pass; commit on `dev`; push. CI runs every job of TECH_SPEC Section 9 and,
   on green, moves the `dev-stable` tag to that commit.
2. The instance's REST sensor polls the tag every ten minutes and the package automation
   runs `tools/ha_deploy.py` by itself. To skip the wait, call
   `shell_command.deploy_device_routines` over the Home Assistant MCP server with
   `return_response` and report the commit and the changed files.
3. If the result says `restart_required`, say so and stop. Never restart. The owner
   restarts, or the opt in window does.
4. After the restart, poll `sensor.device_routines_health` until its `commit` attribute
   equals the pushed sha, run `pytest -m live`, and check Repairs.
5. If the deploy is bad: `shell_command.rollback_device_routines`, say a restart is
   needed, write a regression test.

`tools/ha_deploy.py` is byte identical in the sibling repository ha-device-links (PRD
D15); a change lands in both within the week and the parity CI job keeps that honest. The
file keeps Python 3.11 syntax.

## 6. Privacy

Instance data is anything that describes a real home (PRD 11.3). `local/` holds the raw
captures, the anonymization map and the denylist; none of it is tracked. Fixtures reach
`tests/fixtures/` only through `tools/anonymize.py`. Docs and examples use generic names
only (a living room fan, a robot vacuum), never a real home's names. Diagnostics redact
by default. The privacy check's output masks every match, so even its findings name
nothing.

## 7. Where to look

| Need | File |
| --- | --- |
| Behavior, acceptance scenarios, decisions D1 to D34 | `docs/PRD.md` |
| Module boundaries, blueprint, storage, pipeline, test matrix | `docs/TECH_SPEC.md` |
| Build order, validation steps, exit criteria, session report template | `docs/IMPLEMENTATION_PLAN.md` |
| Choices made during implementation | `docs/decisions-log.md` |
| What waits for the owner, with the default applied meanwhile | `docs/owner-log.md` |
| What a phase proved, with evidence | `docs/validation/phase-N.md` |
| Stage 0 findings and fixtures | `docs/stage0-report.md` |
| The development channel package and its bootstrap | `tools/ha_package/README.md` |
