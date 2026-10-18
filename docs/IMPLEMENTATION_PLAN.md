# Device Routines implementation plan

Oct 13, 2026 · @Jayant Yadav

The build order for Claude Code: Phase 0, Stage 0, then Phases 1 to 4, each with tasks, tests, validation steps and exit criteria. Behavior comes from PRD (public), design from Technical spec (public), private instance facts from Instance context (private). This tab is public and becomes `docs/IMPLEMENTATION_PLAN.md`. Section 8 is the handoff.

Revised 2026-10-18 (decision L32): Phases 2 and 3 are built as one build in parallel lanes with a single restart; Phase 4 is the second build with a second restart; everything the owner has to do is batched into two owner sessions and otherwise deferred in `docs/owner-log.md`. Section 0.1 is the operating model, Sections 4 to 6 the builds, Section 8 the prompts.

Status: Phase 1 done (2026-10-18): v0.1.0 released (`d00fa2f`). Build A (Phases 2 and 3, Section 4) open since 2026-10-18: auto deploy off (Section 0.1.6, recorded in `docs/validation/phase-2.md`); `markers.py` seeded on `dev` (L34); wave A1 done: lanes 1 (core, `028a029`), 2 (blueprint, `ed7d74c`, B01 to B43 green), 3 (adapter, `f9cee6c`) and 4 (attribution, `e2bf4b3`) landed. Wave A2 done: lanes 5 (manager, `473136a`), 6 (store, `e73b194`) and 7 (summary, `59eb0a3`) landed. Wave A3 done: lanes 8 (platforms, `c228ea1`), 9 (actions, `b27977a`), 10 (flow and removal, `905cead`), 11 (repairs, `af265e5`), 12 (websocket, `3ba27ce`), 13 (triggers, `3b7c961`), 14 (Phase 3, `b698210`) and 15 (docs, Health, diagnostics, `6904ddd`) landed; 1619 tests green, coverage 99.83 percent; Wave A4: A4.0 (carry over, 29 items, `b154434`, L57), A4.1 (contracts, `27e16f8`), A4.2 (30 days, `cf03fcf`), A4.3 (golden, `f4ab882`, G5 met, L55) and the A4.5 release change (`af420a2`) landed; 1831 tests green, no xfail, coverage 99.87 percent; no lane worktree open. A4.4 (records, 0.3.0) and A4.5 (exit) are the orchestrator's, in progress. Deployed `8e523cb` (docs only, code equal to the running commit), running `d00fa2f`; restarts pending: none (R1 at the Build A exit). Owner log: 14 open items, none blocking a build (O12 gates v1.0.0 only) (`docs/owner-log.md`). Next: A4.4 (validation records, CHANGELOG and manifest 0.3.0), A4.5 (fast forward `main`, tag `v0.3.0-beta.1`, deploy by hand, auto deploy on, R1 request in O15), then Build B (Section 6).

## 0. Rules of engagement (Claude Code reads this first)

Documents in the repository: `docs/PRD.md` (behavior and the decision register), `docs/TECH_SPEC.md` (design), `docs/IMPLEMENTATION_PLAN.md` (this file: order, validation, rules), `CLAUDE.local.md` (private instance context, gitignored, never committed), `docs/stage0-report.md` (Stage 0 findings), `docs/decisions-log.md` (choices), `docs/owner-log.md` (everything that waits for the owner, with the default taken meanwhile), `docs/validation/phase-N.md` (evidence).

Operating rules:

1. Never restart Home Assistant. Never call `ha_restart` or `homeassistant.restart`, and never reload the config entry as a substitute. Say restart needed and stop that step. Only the opt in automation of TECH\_SPEC 10.2 may restart, and only once Jayant turns it on.
2. Read only probes and, since 2026-10-17 (decision L26), write probes and live write scenarios against the live instance are pre approved. Every write still needs a read before it and a read after it proving the state was restored or is the intended end state. Restarts (rule 1) and steps only Jayant can take (copying files into the config directory, operating devices, looking at the UI) still need him. Where a phase below says approval for a live write, read it as this rule.
3. Nothing from `CLAUDE.local.md`, `local/` or the live instance goes into a commit, fixture, test, doc, issue, pull request or commit message. The pre commit privacy check must pass; never bypass hooks.
4. Work on `dev`. Conventional commits. Push when the local gates pass. Merge `dev` into `main` only at a build exit with green CI, as a fast forward (no merge commits anywhere: `main` requires linear history).
5. One build at a time (Section 0.1). Inside a build, lanes run in parallel against the interface contracts the plan pins; inside a lane, tasks in order. A build does not start before the previous build's exit criteria are recorded.
6. Tests ship in the same commit as the code they cover. Coverage never drops below 95 percent on `custom_components/device_routines`.
7. Decisions: proceed on the PRD defaults without asking. Record every choice the PRD and spec do not cover in `docs/decisions-log.md` (date, context, options, choice, consequence). Owner questions go to `docs/owner-log.md` with the default applied meanwhile (rule 14); ask in chat only when a default would be unsafe.
8. Style: no em dash character anywhere; a translation key for every user facing string; `ruff` and `mypy --strict` clean before every commit.
9. Keep `CHANGELOG.md` current under Unreleased with every user visible change.
10. Update the Status line at the top of this file in every commit that completes a task, and end every working session with the session report of Section 9.3 in chat.
11. When a probe or a test contradicts the PRD or the spec: stop the task, write the finding in the Stage 0 report or the decisions log, propose the smallest design change, and continue with it unless it touches a hard constraint (PRD Section 3), in which case ask.
12. Harness first. Every behavior is proven in the harness (`pytest-homeassistant-custom-component`, a real core with time travel and cold starts over restore state) before it is deployed. Live validation confirms; it never discovers. A live finding becomes a harness test before it is fixed.
13. One restart per build. Pushes to `dev` continue throughout a build, but the instance's auto deploy switch is off while a build is open (Section 0.1.6), the finished build is deployed by hand from its tag, and one owner restart loads it. Scenarios that need a restart are staged before a restart that happens anyway (Section 5.2); no scenario gets a restart of its own.
14. Owner items never stop the work. Anything that needs Jayant (a look, a device operated, a token, a decision, an approval of an outward facing action) is written to `docs/owner-log.md` with what, why, the default taken meanwhile and the pause point it is needed by. A session stops only at a hard stop (Section 0.1.5).
15. Definition of done for a task: code, tests, translations, `quality_scale.yaml` (every rule the task satisfies moves to `done` with the test that proves it), the user guide, README status, `CHANGELOG.md`; local gates green; pushed; CI green.

Definition of done for a build: every task done; the harness validation recorded in `docs/validation/phase-N.md`; exit criteria met; `main` fast forwarded; the beta tag created; the deploy and restart requested through the owner log and the Status line. The live rows of the record are filled after the restart (Sections 5 and 6).

What you have: the repository, the `gh` CLI with Jayant's authentication, the Home Assistant MCP server (reads, service calls and WebSocket commands through `ha_call_service`), the local test harness, the Agent tool for lanes. What you do not have: file access to the Home Assistant config directory, and restarts.

### 0.1 Operating model (from 2026-10-18, decision L32)

#### 0.1.1 Builds and restarts

| Build | Content | Restart | Live validation | Release |
| --- | --- | --- | --- | --- |
| A (Section 4) | Phase 2 (every P0 row) and Phase 3 (every P1 row, the WebSocket API) built together in the harness | R1, the owner's, after the build exit | Section 5, in a session that runs while Build B starts | `v0.3.0-beta.1` at the harness exit; `v0.3.0` after live validation A (L33) |
| B (Section 6) | Phase 4: FR-R9, FR-R10, FR-M1, the console, publication | R2 after the build exit | Section 6.3, S9 and the console | `v1.0.0-beta.1` at the harness exit; `v1.0.0` after live validation B and the owner's console look |
| Publication | brands pull request, HACS default submission, channel switch | R3, optional, only if the owner switches to the HACS channel | the HACS install | none |

Opportunistic restarts: the owner restarts for monthly Home Assistant updates and other reasons of his own. Every such restart is announced in chat or the owner log beforehand when possible; the session then stages the pending scenarios of Section 5.2 before it and reads after it, exactly as for R1 and R2.

Why two restarts are enough: every live capability the routines need was already probed on the instance in Stage 0 (blueprint install V5, automation writes V6, helpers V7, take control V8, device attachment V9 and C4, time triggered contexts V3), and the harness runs the same core version with cold starts over restore state. What a restart can still reveal is UI rendering and the in process helper dispatch under a system user, and both are checked right after R1.

#### 0.1.2 Lanes, waves and the orchestrator

A build is a sequence of waves; a wave is a set of lanes that touch disjoint files and run in parallel; a lane is one agent with one brief (template 9.7). The orchestrating session dispatches the lanes of a wave together, integrates their results, runs the whole suite, and moves to the next wave. The orchestrator writes code itself only for the shared files and the integration work of wave A4.

Lane protocol:

1. Each lane works in its own git worktree on a branch `lane/<name>` cut from `dev` (`git worktree add ../dr-<name> -b lane/<name> dev`, or the Agent tool's worktree isolation). The worktree has no virtual environment: `ln -s <repo>/.venv .venv` first, so the hooks and gates run.
2. A lane owns the files its task lists. Shared files (`strings.json`, `translations/en.json`, `icons.json`, `const.py`, `sentences/en.json`, `tests/test_repository.py`) may be edited additively for the lane's own keys; `CHANGELOG.md`, `quality_scale.yaml`, `manifest.json`, `README.md` and this file are the orchestrator's. A lane that must change an interface contract (Section 4.2) stops and reports instead.
3. A lane commits on its branch with conventional commits and the hooks on, runs `ruff`, `mypy`, its own tests and the whole suite before its last commit, and never pushes. Its final report lists: commits, files, the tests that prove each requirement, anything deferred, and the shared file edits it made.
4. The orchestrator rebases each lane branch onto `dev` (`git rebase dev` in the worktree), resolves the rare shared file conflict, fast forwards `dev`, runs the whole suite with coverage, pushes, and deletes the worktree and branch. No merge commits.
5. Lanes run with the model and effort of the orchestrator unless the brief says otherwise; pure module lanes and docs lanes may run on a cheaper model.

#### 0.1.3 Interface contracts

Section 4.2 pins every name and signature two lanes share before wave A1 starts. A lane implements its side against the contract and tests against fakes of the other side; wave A4 replaces the fakes with the real modules and the contract tests prove they agree. A contract change is a plan edit by the orchestrator, recorded in the decisions log when it changes the spec.

#### 0.1.4 The owner log

`docs/owner-log.md` is the single register of what waits for Jayant (template 9.5): an id (O1, O2, ...), the item, why it is his, the default the work takes meanwhile, the pause point it is needed by (R1, R2, release 1.0, none), and the status. Items are grouped into the two owner sessions of Section 8.1 so the owner does them in one sitting each. An item marked blocking is the only kind that may hold a release; none holds a build.

#### 0.1.5 Hard stops and the resume protocol

A session stops working only when:

- the next step of every open lane needs a restart that has not happened (never true while a build is open, because the next build's harness work can always start);
- every option on the table breaks a hard constraint of PRD Section 3;
- the context is exhausted (the normal end of a long session).

Everything else continues: owner items go to the log, decisions to the decisions log, a live scenario that needs a restart to the staging table.

Resume protocol. The Status line at the top of this file always holds, in this order: the last completed phase and release; the open build and wave with the lanes finished and in flight; the deployed commit versus the running commit (restarts pending); the owner log open and blocking counts; the next task. Every session starts by reading the Status line, the tail of `docs/decisions-log.md`, the open items of `docs/owner-log.md` and, when a restart just happened, Section 5.3 or 6.3. Section 8.3 is the prompt. A lane's unfinished worktree is listed in the Status line with its branch, so the next session can resume or discard it.

#### 0.1.6 Deploy stance during a build

While a build is open, `input_boolean.device_routines_auto_deploy` is off (a live write under rule 2, with a read before and after and a line in the validation record), so pushes to `dev` reach GitHub and CI but not the instance's disk, and an incidental owner restart loads nothing new. At the build exit the orchestrator calls `shell_command.deploy_device_routines` with `ref` set to the beta tag, reports the commit and the changed files, turns auto deploy back on, writes the restart request into the Status line and the owner log, and continues with the next build. The deploy tool is idempotent and refuses nothing here; the post restart check and the rollback guard (L13, L16, L17) stay as they are.

Known hazard: between a deploy and the restart, Home Assistant still runs the old code but imports new modules lazily (diagnostics download, a Repairs fix flow, an options flow). The deploy request in the owner log says: restart before opening diagnostics, Repairs or the options of Device Routines.

## 1. Phase 0: foundation and pipeline (no product behavior)

Done 2026-10-14; evidence in `docs/validation/phase-0.md`. The text below is the record of what was asked.

Goal: a public repository with green CI, privacy tooling, the deploy tool and package, and a skeleton integration whose Health sensor proves that a commit on `dev` reaches the running instance with no human in the loop except the restart.

Tasks:

1. **0.1 Repository.** `gh repo create <owner>/ha-device-routines --public` with the MIT license and the description Device level routines for Home Assistant: schedules, run timers and a plain language schedule summary on every device page; topics `home-assistant`, `hacs`, `automation`, `blueprint`, `schedule`, `timer`. The first commit contains only `.gitignore` (TECH\_SPEC 8). Create `dev` from `main`. Protect `main`: required status checks (every CI job), no force pushes, no deletions, linear history. Enable Dependabot.
2. **0.2 Skeleton.** The layout of TECH\_SPEC 9, `pyproject.toml` (ruff, mypy strict, pytest, coverage), `requirements_test.txt` pinned to the core version named in `CLAUDE.local.md`, `.pre-commit-config.yaml` (ruff, mypy, privacy check, style check), `LICENSE`, `README.md` (what it is, HACS custom repository install, badges), `CHANGELOG.md`, `hacs.json`, `brand/` placeholders, `.github/ISSUE_TEMPLATE/` (bug report asking for redacted diagnostics; feature request).
3. **0.3 Integration skeleton.** `manifest.json` (version 0.0.1), `const.py`, `__init__.py` setup and unload, the zero field `config_flow.py`, the hub device with the Health sensor (`health.py`), `strings.json`, `translations/en.json`, `icons.json`, `quality_scale.yaml` with every rule listed as todo or exempt with a reason, `diagnostics.py`. hassfest and the HACS action pass.
4. **0.4 Privacy tooling.** `tools/make_denylist.py`, `tools/anonymize.py`, `tools/privacy_check.py`, `tools/privacy_allowlist.txt`, `tools/style_check.py`, each with unit tests. Build `local/captures/registries.json` from MCP reads (entity, device, area, floor and label registries) and generate `local/denylist.txt`. Verify that the hook blocks a commit containing a denylisted name (S10, first half).
5. **0.5 Deploy tool.** If `ha-device-links` already has `tools/ha_deploy.py`, generalize it to the TECH\_SPEC 10.1 interface and open a pull request there with the identical file; otherwise write it here and open the backport pull request. Unit tests per TECH\_SPEC 10.1.
6. **0.6 Home Assistant package.** `tools/ha_package/device_routines_dev.yaml` and `tools/ha_package/README.md` (bootstrap steps, how the restart policy works, how to roll back by hand, how to switch to the HACS channel later).
7. **0.7 CI.** `ci.yml` with every job of TECH\_SPEC 9 including `promote`; `release.yml`; both green on the skeleton. Confirm that the `dev-stable` tag appears after the first green push to `dev`.
8. **0.8 Instruction files and docs.** `CLAUDE.md` (the PRD 11.4 content, the loop of TECH\_SPEC 10.5 and the rules of Section 0 here); `CLAUDE.local.md` from the Instance context tab, never committed; `docs/PRD.md`, `docs/TECH_SPEC.md` and `docs/IMPLEMENTATION_PLAN.md` from the exported tabs; `docs/decisions-log.md` started.
9. **0.9 Bootstrap on the instance (Needs Jayant).** Jayant copies `tools/ha_deploy.py` to `/config/tools/ha_deploy.py` and the package to `/config/packages/device_routines_dev.yaml` (or merges its sections into `configuration.yaml` when packages are not enabled), sets `<owner>`, checks the configuration and restarts. You then verify over MCP that `shell_command.deploy_device_routines`, `sensor.device_routines_dev_stable` and the three automations exist.
10. **0.10 End to end proof (this is Stage 0 item V11).** Push a trivial change to `dev`; watch CI go green and `dev-stable` move; watch the rest sensor change and the deploy automation run (`ha_get_automation_traces`); read the notification; ask Jayant to restart; poll `sensor.device_routines_health` until `commit` equals the sha; run `shell_command.rollback_device_routines` over MCP; ask for a restart; confirm that Health shows the previous commit; deploy again. Record every step with timestamps in `docs/stage0-report.md`.

Tests: `tests/tools/` for the deploy tool (ref resolution, idempotency, download and extract from a local tarball, a compileall failure leaving the old directory untouched, backup rotation keeping five, atomic swap, `changed_files` classification, rollback and the double rollback refusal, status output, the HACS managed warning), the privacy check (every generic pattern, a denylist hit, an allowlist pass, commit message scanning), the anonymizer (deterministic, complete, idempotent) and the style check; `tests/integration/test_setup.py` (setup, unload, Health attributes with and without `.deployed`, the zero field flow, single instance).

Validation: CI green on `dev` and `main`; the `dev-stable` tag present; S10 second half (a throwaway branch with a token shaped string fails CI); the V11 record complete.

Exit criteria: all of the above; `main` at the Phase 0 merge; no release tag yet.

Needs Jayant: the GitHub user name; the bootstrap of task 0.9; two restarts in task 0.10.

## 2. Stage 0: validation probes

Done 2026-10-17; every assumption closed or amended in `docs/stage0-report.md`, whose cleanup items C2, C3, C5 and C6 are now owner log items O1, O3, O4 and O5.

Goal: close or amend every PRD assumption before product code, and collect anonymized fixtures.

Procedure for every item: write the plan for the item in `docs/stage0-report.md` first (what, how, what proves it, what restores it); run it; record the evidence; close the assumption or write the amendment and its design consequence. Throwaway artifacts are named `stage0_*` and removed at the end, with a read proving the removal.

| Item | Method | Approval |
| --- | --- | --- |
| V2 (A3, A4) | Over MCP, for every automation: read the entity's config attribute and the reference helper results through `ha_eval_template` and `ha_config_get_automation`; record how the YAML defined automation appears; capture raw into `local/captures/`; anonymize into `tests/fixtures/automations/`; seed the golden corpus | Read only |
| V3 (A9 as amended) | With Jayant operating the four devices he names (one each on Z-Wave, Zigbee, Matter and Wi-Fi) by hand, by app and by voice, and with a time triggered `stage0_` automation changing one of them: record `state_changed`, `automation_triggered` and `script_started` events with their contexts into `local/captures/`; replay them through the attribution classifier; confirm that time triggered runs produce parentless contexts and that the map still classifies them as automation | Read only, plus one `stage0_` automation (write, approval) |
| V4 (A12) | Check for AI Task entities; if Jayant creates one on the local endpoint, one `generate_data` call with a synthetic automation | Read only |
| V5 (A1, A8) | A `stage0_` throwaway integration installs a `stage0_` blueprint with sections, a condition selector, `enabled: !input` on a trigger and on a condition, the sentinel pattern and a timer finished trigger if the platform offers one; confirm the form renders and validates | Write (config files), approval |
| V6 (A2) | From the throwaway integration, create, update and delete one `stage0_` automation through the candidate write path; find out whether the editor's lock is reachable; confirm other automations keep running (`current`, `last_triggered`) | Write, approval |
| V7 (A5) | Create and delete a `stage0_` timer and a `stage0_` schedule helper with chosen entity ids and the label; in the harness, confirm that a restored timer which expired while stopped fires `timer.finished` at start | Write, approval; harness for A5b |
| V8 (A11) | Take control of the `stage0_` blueprint automation; confirm the id is kept and record the resulting shape | Write, approval |
| V9 (A10) | Attach a `stage0_` config entity to the sandbox device; confirm placement on its device page; remove it | Write, approval |
| V10 (A5b, A6, A7) | Harness tests: a restored expired timer, adjacent schedule blocks at midnight, DST dates | Harness only |
| V12 (A13) | Harness: a time trigger and a time condition against a `datetime` entity and against a timestamp sensor; a restored `datetime` entity across a restart; record which path the blueprint will use | Harness only |
| V13 (A14) | Register a `stage0_` trigger and condition from the throwaway integration; confirm they appear in the editor pickers with device, area and label targets | Write (config files), approval |

Report format for `docs/stage0-report.md`: one section per assumption with Status (closed, amended, deferred), Evidence, Consequence (which spec paragraph changes) and the fixtures produced. A final section records which decision defaults applied.

Exit: every assumption closed or amended; every write item done or deferred by Jayant; fixtures committed only after anonymization and a privacy check; the spec updated wherever amended; `main` updated.

Needs Jayant: the four V3 devices; approvals for V3 (the automation), V5, V6, V7, V8, V9 and V13; optionally an AI Task entity for V4.

## 3. Phase 1: Schedule summary (the read only product)

Done 2026-10-18, v0.1.0; evidence in `docs/validation/phase-1.md`. Section 3.1 is the audit of 2026-10-18 and the work it adds to Build A.

Goal: every device that any automation acts on shows a trustworthy Schedule sentence; the hub exists; the global settings scaffold is in place; release v0.1.0.

Tasks:

1. **1.1 Pure modules.** `models.py`, `domains.py` (the profiles discovery and verbs need), `parser.py` and `parser_grammar.py`, `nextrun.py`, `sentence.py`, `conflicts.py` (detection only, no Repairs yet), `settings.py` (`schedule_scope`, `time_format` and defaults for the rest).
2. **1.2 SummaryCoordinator** in `summary.py`: discovery, recompute triggers, debounce, next run timers, sensor lifecycle per scope.
3. **1.3 Sensor platform.** The Schedule sensor with the FR-S4 attributes; the hub Routines sensor (count 0 and an empty list for now), the Problem sensor and the Health sensor from Phase 0.
4. **1.4 Options flow** settings page; `diagnostics.py` redaction complete; `repairs.py` with `adapter_incompatible` only.
5. **1.5 ha\_adapter.py** read capabilities and `check`.
6. **1.6 Golden corpus.** The Stage 0 fixtures plus synthetic cases; expected lines reviewed with Jayant once (he confirms or corrects sentences in chat; a correction becomes a grammar fix with a test, never a special case).
7. **1.7 Docs.** `docs/user-guide.md` section Reading the Schedule sensor; README feature description without instance names.

Tests: unit tests for every grammar rule; the golden corpus; next run property tests (weekday, midnight crossing, DST on 2026-03-08, 2026-11-01, 2026-03-29 and 2026-10-25); the sentence cap; conflicts; coordinator tests (debounce, recompute on each event, scope changes creating and removing sensors, and the assertion that no interval or `time_pattern` listener exists); options flow; diagnostics redaction; Health.

Validation, live and read only, after the deploy and restart: list the devices with automations over MCP and compare with the set of Schedule sensors; the share of `source: none`; ten sentences spot checked by Jayant; no Repairs issues; `pytest -m live` green.

Exit: tests green; coverage at least 95; the live validation recorded; `CHANGELOG.md` and `manifest.json` at 0.1.0; tag `v0.1.0`; the release built by `release.yml`; the HACS custom repository install verified by Jayant on a second instance, or recorded as deferred.

Needs Jayant: the sentence review (one session) and one restart.

### 3.1 Audit of the completed work (2026-10-18)

Checked: the whole suite (99.5 percent coverage, every test green on core 2026.10.2), CI (green on `8229b9e`, `dev-stable` there, `v0.1.0` released, `main` at `d00fa2f`), the instance read only (Health `ok` on `d00fa2f`, last good commit equal, auto deploy on, auto restart off, no open issue), the docs against the code, the quality scale against the code, the cleanup items, the sibling pull request.

| Id | Finding | Where it goes |
| --- | --- | --- |
| F1 | `quality_scale.yaml` was not refreshed in Phase 1: `entity-event-setup`, `dynamic-devices`, `docs-data-update`, `common-modules`, `docs-known-limitations` and the Phase 1 half of `repair-issues` and `diagnostics` are satisfied by shipped code and tests but still read `todo` or describe Phase 1 as future. Rule 15 now makes the file part of every task's definition of done | Build A, lane 15 (docs) refreshes every rule against the code; the orchestrator checks the file at every wave |
| F2 | `README.md` still says Phase 1 is being built | Lane 15 |
| F3 | G5 says at least 90 percent of the golden corpus parses; the corpus parses 45 of 56 items (80 percent), and the Phase 1 exit recorded it as a pass. The corpus deliberately holds golden negatives (multi automation controllers) that must read as custom logic | Build A task A4.3: classify the 11 unparsed items; extend the grammar only for constructs that can be read with zero guessing (each with a test); then either the measure is met or a decision entry amends G5's measure to exclude the golden negatives; owner log O14 lets Jayant override |
| F4 | `local/live.env` was never created, so `pytest -m live` has never run; the Phase 1 record says so. MCP reads covered the same checks | Owner log O2 (R1 session); until then the live rows use MCP reads |
| F5 | The adapter check logs nothing when a capability fails or recovers (`log-when-unavailable` promised it for task 1.5) | Lane 3 |
| F6 | TECH\_SPEC 9 and 13 still say Python 3.13 (superseded by L1), 12 says one point in time listener per device (superseded by L30), and PRD 0.2 and 13.2 still ask for a per item approval of write probes (superseded by L26) | Lane 15: a note at each place pointing at the decision, no rewrite of the owner's PRD text |
| F7 | The sibling backport jayanty/ha-device-links#59 is still open, so the `deploy-tool-parity` job records a skip and proves nothing | Owner log O6 |
| F8 | The HACS custom repository install was never tried on a second instance | Owner log O7, deferred indefinitely |
| F9 | `tests/test_repository.py` collects translation keys for the `datetime` platform nowhere, and allows none of `homeassistant.components.websocket_api`, `panel_custom` or `http`, which Build A and B need as public component APIs | Lanes 6, 10 and the Build B console lane edit the lists additively; the orchestrator reviews the diff of that file at every wave |
| F10 | The instance's auto deploy switch deploys every green `dev` push to the production disk; an incidental restart would load unvalidated code | Section 0.1.6: auto deploy off while a build is open |
| F11 | Five owner restarts in five days, and the old Phase 2 to 4 text asked for at least seven more | Decision L32: two restarts for everything that is left |

## 4. Build A: Phases 2 and 3 in the harness

Goal: every P0 and P1 requirement, the blueprint, the compiler, attribution, the device page controls, skip and pause, the actions, sync back, self healing, removal, the weekly schedule, keep alive, pulse, the late start window, integration triggers and conditions, the AI path, conflicts to Repairs, marker M9, the complete settings catalog and the WebSocket API, all proven in the harness; `main` fast forwarded; `v0.3.0-beta.1` tagged and deployed to the instance's disk; R1 requested.

### 4.1 Scope

Phase 2 (PRD 13.3): FR-R1, R3, R5, R6, R11 to R15; the blueprint; the compiler; attribution; device page entities including Skip next, Paused until and Resume; the skip and pause actions; the write path; sync back; markers M1 to M8; refusals; the self healing of PRD 3.1; removal. Phase 3: FR-R2, R4, R8, R17; the late start window; the AI summary; conflicts; marker M9; the complete settings catalog; the WebSocket API of PRD 7.5.

Not in Build A: FR-R9 (the `extra_conditions` input exists in schema 1 and round trips, but no editor path beyond the blueprint form, and no documentation of it until Build B), FR-R10 (sun relative times are a schema 2 change in Build B, which exercises the migration machinery of task A2.2 for real), FR-M1, the console.

### 4.2 Interface contracts

Names two or more lanes share. Signatures not shown here are in TECH\_SPEC 3 and 4 and bind as written there; L28 applies (the parser returns structure, `sentence.Writer` renders).

Pure modules (standard library only; `tests/test_repository.py` checks):

| Module | Contract |
| --- | --- |
| `models.py` | `RoutineSettings` as today; `Status`, `Source`, `Days`, `Weekday`, `Pulse`, `Problem`, `CompileError`, `CompiledInputs(inputs)`, `SummaryItem`, `Conflict` as today. New: `RoutineView` moves here as a frozen dataclass with the TECH\_SPEC 4.1 fields (`device_id`, `device_name`, `area_id`, `automation_id`, `automation_entity_id`, `settings`, `status`, `enabled`, `paused_until`, `skipped_action`, `next_action`, `sentence`, `items`, `conflicts`, `override`, `last_change_source`), typed (pinned at the wave A1 dispatch): `device_id: str`, `device_name: str`, `area_id: str | None`, `automation_id: str`, `automation_entity_id: str | None`, `settings: RoutineSettings`, `status: Status`, `enabled: bool`, `paused_until: datetime | None`, `skipped_action: Occurrence | None`, `next_action: Occurrence | None`, `sentence: str | None`, `items: tuple[SummaryItem, ...]`, `conflicts: tuple[Conflict, ...]`, `override: bool`, `last_change_source: Source | None` |
| `compiler.py` (new) | `BLUEPRINT_SCHEMA_VERSION: Final = 1`; `BLUEPRINT_PATH: Final = "device_routines/device_routine.yaml"`; `EVENT_ACTION_SKIPPED = "device_routines_action_skipped"`; `EVENT_TIMER_CAUGHT_UP = "device_routines_timer_caught_up"`; the sentinel entity ids `UNUSED_TIMER`, `UNUSED_SCHEDULE`, `UNUSED_SWITCH`, `UNUSED_DATETIME` (`<domain>.device_routines_unused`); `INPUT_KEYS: tuple[str, ...]` in the TECH\_SPEC 5.2 order; `HelperRefs(device_id, timer_entity, schedule_entity, override_entity, paused_until_entity)` with the sentinels as defaults; `validate(settings, profile) -> list[Problem]`; `compile(settings, profile, refs) -> CompiledInputs` (raises `CompileError` carrying the first problem when `validate` is not empty); `decompile(inputs) -> RoutineSettings` (raises `CompileError` with key `invalid_inputs` when `is_valid_shape` is false); `is_valid_shape(inputs) -> bool`; `refs_of(inputs) -> HelperRefs`. Landed in lane 1 (`028a029`) with (decision L38): `canonical(settings)` (`decompile(compile(s)) == canonical(s)`), `has_refused_action(inputs, device_class)` for sync back, `INPUT_DEFAULTS`, `REQUIRED_KEYS`, `PROBLEM_KEYS`, `UNUSED_TIME`, `MAX_DURATION_MIN`, `MAX_LATE_START_MIN`; for a profile without an on action `on_action` holds the off action |
| `markers.py` (seeded on `dev` before wave A1, decision L34) | TECH\_SPEC 3.4 as written; already on `dev`: `AUTOMATION_ID_PREFIX`, `BLUEPRINT_PATH` (the definition; `compiler.BLUEPRINT_PATH` re exports it), `automation_id(device_id)`, `has_routine_id(config) -> bool` (M1 alone, for take control detection) and `is_owned(config)`; lane 1 adds `LABEL_ID = "routines"`, `LABEL_NAME = "Routines"`, `CATEGORY_NAME = "Device Routines"`, `ICON = "mdi:calendar-clock"`, `REPLACED_LABEL_ID = "replaced_by_routine"` (Build B); `Presentation(alias, description, icon)`; `presentation(device_name, phrases, *, formerly=False) -> Presentation` reads the alias and description templates from the phrase table (`routine_alias`, `routine_description`, `formerly_managed`); `alias_is_generated(alias, names, template=DEFAULT_ALIAS_TEMPLATE)` (the manager passes `phrases["routine_alias"]`); `config_hash(config)`; `slugify(text)`; `entity_id_for(device_name) -> str` (`automation.routine_<slug>`); `helper_slug(device_name, device_id, taken: Collection[str]) -> str` (the device slug, or the slug plus the first six hex characters of `automation_id`'s hash when taken) |
| `nextrun.py` | `expected_state(settings, now, schedule_state)` as today; new `SkipTarget(verb, at, paired_end, paused_until)` and `skip_target(settings, now, paused_until, schedule_state, sun) -> SkipTarget | None` (D18: a window start pairs its end; D19: a window end or a running countdown is skipped alone; pressing again extends from the current `paused_until`). Landed in lane 1: `skip_target(..., *, countdown_ends: datetime | None = None)` (pass the end of an active timer; the target is the countdown when `target.at == countdown_ends`, and the manager cancels the timer); `routine_occurrences(settings, now, schedule_state=None, lookups=None, *, countdown_ends=None, not_before=None)` lists the coming actions, the first being the one the state shows (lane 7 passes `not_before=paused_until`); a weekly schedule reads its `next_event` from `lookups.entity_times[schedule_entity]`, and Skip next outside a block returns None until lane 14 adds the block ends (L38) |
| `sentence.py` | `Writer` gains `skipped(verb, at, now) -> str` ("Skipped, on Thu 5:00 PM", pass the next action that really runs after the pause), `paused(until, now) -> str`, `routine_off() -> str` and `routine_kind(*, detached=False) -> str`, landed in lane 1 (lane 7 consumes them); phrases added to `sentences/en.json`: `state_skipped` ("Skipped, {action} {when}"), `state_paused` ("Paused until {when}"), `state_routine_off` ("Routine off"), `routine_alias`, `routine_description`, `formerly_managed`, `kind_routine`, `kind_detached`; the 40 character cap applies to every new state |
| `settings.py` | `GlobalSettings` complete with every PRD 10.4 key; `OPTIONS_VERSION = 2`; `migrate(options, version)` from 1 |

Integration modules:

| Module | Contract |
| --- | --- |
| `ha_adapter.py` | Capabilities: `CAPABILITY_WRITE = "write_automations"`, `CAPABILITY_BLUEPRINT = "install_blueprint"`, `CAPABILITY_HELPERS = "create_helpers"`, `CAPABILITY_RESTORE = "restore_state"`; `check()` fills all. Functions: `async_read_automation(hass, automation_id) -> Mapping | None` (from the file); `async_write_automation(hass, automation_id, config, expected_hash: str | None) -> WriteResult(hash, created)` (refuses with `NotOwnedError` unless `markers.is_owned(config)`; `WriteConflictError` when the file hash moved twice); `async_delete_automation(hass, automation_id)` (file entry plus registry entry); `file_hash(hass) -> str`; `async_install_blueprint(hass, text)`, `installed_blueprint_text(hass) -> str | None`; `async_ensure_system_user(hass, user_id: str | None) -> str`; `async_create_helper(hass, user_id, domain: Literal["timer", "schedule"], name, **fields) -> str` (entity id), `async_update_helper`, `async_delete_helper`; `async_update_registry_entity(hass, entity_id, *, new_entity_id, labels, device_id)`; `ensure_label(hass, label_id, name, icon) -> str`; `ensure_category(hass, scope, name, icon) -> str`; `missed_timer_finishes(hass, timer_entity_ids) -> list[str]`; `is_detached(config) -> bool`; `automation_state(hass, entity_id) -> State | None`; (lane 7) `automation_blueprint(hass, entity_id)` and `AutomationRefs.blueprint`, because a blueprint automation's `raw_config` is rendered and has no `use_blueprint`, so ownership is judged on the file entry or on `{**config, "use_blueprint": blueprint}`, never on `raw_config` alone (L43); logs once at WARNING when a capability fails and once at INFO when it recovers (F5). Landed in lane 3 (`f9cee6c`) with these refinements (decision L37): `file_hash` is a callback returning the hash of the file as the adapter last read or wrote it, so the guard is `file_hash(hass)` taken right after `await async_read_automation(...)` with no await between; `WriteResult.hash` is the file hash after the write, not `markers.config_hash`; `async_write_automation` reloads the id itself; `async_delete_automation -> bool` (whether the file held it); `async_install_blueprint -> bool`; `installed_blueprint_text` is blocking (call it in the executor); `async_update_registry_entity` and `ensure_*` are callbacks, also taking `area_id`, `icon` and `categories`; `async_create_helper(..., *, entity_id=None, labels=None, **fields)` takes no device (L36); errors are `AdapterError`, `NotOwnedError`, `WriteConflictError`, `HelperError(code)`. Lane 10 adds `async_release_automation(hass, automation_id, config)` (the one path that writes an entry without M2, and only over an entry that is owned at that moment: take control on removal) and `async_remove_system_user(hass, user_id)` (L23 removes the user with the entry) |
| `store.py` (new) | `STORAGE_KEY = "device_routines"`, `STORAGE_VERSION = 1`; `OwnedRecord(device_id, target_entity, last_hash, last_valid_inputs, previous_inputs, schema, alias_history: tuple[str, ...])`; `StoreData(owned, opted_in, opted_out_at, removed_devices_at, blueprint_hash, blueprint_schema, ai_cache)`; `RoutineStore(hass)` with `async_load()`, `async_save()`, `data`; `migrate_store(version, minor, data) -> dict`. Landed in lane 6 (`e73b194`): also `async_delay_save(delay=SAVE_DELAY)`, `StoreData.to_dict` and `from_dict` (`opted_in` a set), `AiCacheEntry(text, created)`, `StoreVersionError`; a newer stored version, minor included, is refused and left on disk (decision L42) |
| `migration.py` (new) | `async_migrate_entry(hass, entry)` through `settings.migrate`; `async_migrate_blueprint_schema(hass, manager, store) -> list[str]` (the TECH\_SPEC 4.11 rewrite of every owned automation, returning the ids that failed). Landed in lane 6: `manager` satisfies `SchemaMigrationTarget` (`async_ensure_blueprint() -> bool`, `async_write_settings(automation_id, settings) -> None`); `DECOMPILERS` per old schema (Build B freezes the schema 1 decompiler there); `decompile_inputs(inputs, schema)`. Lane 5 wires the migration into setup and raises `automation_load_failed` for the returned ids |
| `attribution.py` (new) | `RoutineRuntime(device_id, active, paused, respect_manual, expected: Literal["on", "off"] | None, inactive_state: str)` (`expected` is the window's expectation from `nextrun.expected_state`; a state equal to `inactive_state` reads as off, any other available state as on; `inactive_state` added at the wave A1 dispatch, because a vacuum, cover, lock or climate state cannot be compared with on and off otherwise); `class RoutineLookup(Protocol): def routine_for(self, entity_id) -> RoutineRuntime | None`; `class OverrideSink(Protocol): async def async_set_override(self, device_id, on: bool | None, source: Source, new_state: str) -> None` (called for every classified change of a watched entity; `True` or `False` sets or clears the override, `None` records `source` and `new_state` only: automation changes, and manual changes while the routine is paused, inactive or not respecting manual changes); `Attributor(hass, lookup, sink)` with `async_start()` (a coroutine), `async_stop()` (a callback, not awaited), `watch(entity_id)`, `unwatch(entity_id)`, `classify(context) -> Source` (landed in lane 4, `e2bf4b3`; the sink is called in event order through an eagerly started task, so the manager applies its state before its first await; decision L35); `MAP_LIMIT = 10_000`, `MAP_TTL = timedelta(hours=24)`, `STARTUP_GRACE = timedelta(seconds=30)` |
| `manager.py` (new) | `RoutineManager(hass, entry, store, summary, attributor_factory)` with every TECH\_SPEC 4.1 method by name; implements `RoutineLookup`, `OverrideSink` and `RoutineItemsProvider`; `async_add_listener(callback: Callable[[ManagerEvent], None]) -> CALLBACK_TYPE` with `ManagerEvent(kind: Literal["routine_changed", "schedule_changed", "settings_changed", "health_changed"], device_id: str | None)`; fires bus events `device_routines_paused` and `device_routines_resumed` with `device_id`, `automation_id`, `until`; listens to `EVENT_ACTION_SKIPPED` and re emits it to its listeners. Blueprint facts the manager must honor (lane 2, decision L40): a pause ends at its stored time by clearing Paused until (setting it to the instant it already holds is no state change and runs no catch up); an early Resume sets it to now or clears it; Skip next on a window end also turns the Manual override on, so the pause end's catch up keeps the device as it is until the next scheduled time clears the override (D19), and Resume clears an override the skip set; Skip next on a running countdown cancels the timer before writing Paused until. Landed in lane 5 (`473136a`, decision L44): result types `OptResult`, `UpdateResult(view, problem)`, `ActionResult`, `ActionResults(results, ignored)`, `TargetResolution(device_ids, ignored)` with `IgnoredTarget(target, kind, reason)`, `DeviceChoice`, `HealthInputs`, `RestoredRuntime`; the patch is a mapping of `RoutineSettings` field names (`apply_patch`); `ManagerEvent` gains optional `reason` and `data`; entity facing methods `async_set_manual_override(device_id, on)`, `async_restore_runtime(device_id, RestoredRuntime)`, `restore_data(device_id)`, `entity_id_for(device_id, key)`, `unavailable_reason(device_id)`, `candidates(device_id)`; fix flow methods `async_restore_last_valid`, `async_regenerate`, `async_retry_write`, `async_create_new_routine`; `async_run_action(action, target, *, until, duration)`; `health_inputs()` |
| `summary.py` | `RoutineSummary(items, paused_until, skipped_action, status)`; `class RoutineItemsProvider(Protocol): def routine_summary(self, device_id) -> RoutineSummary | None`; `SummaryCoordinator.set_routine_provider(provider)`; `async_refresh_device(device_id)`; routine items sort first; the state reads the paused, skipped and off forms of FR-S4. Landed in lane 7 (`59eb0a3`, decision L43): `KIND_ROUTINE`; `routine_summary` is synchronous and asked at every view refresh for indexed devices and devices named through `async_refresh_device`; `set_routine_provider` and `async_refresh_device` are callbacks (not awaited); `skipped_action` is the action Skip next skipped (as `RoutineView.skipped_action`), while the state names the next action that really runs, which the summary computes from the owned automation's inputs; the manager calls `set_routine_provider(manager)` at setup and `async_refresh_device` after every routine change and for every routine after reconcile |
| `maintenance.py` (new) | `MaintenanceAction` enum (`clean_up_now`, `rebuild_index`, `reinstall_blueprint`, `refresh_summaries`); `async_run(hass, target, action, dry_run) -> MaintenanceReport(action, changed: list[str], would_change: list[str])`, where `target` satisfies `MaintenanceTarget`, a `Protocol` lane 6 defines in `maintenance.py` and the manager implements (amended at the wave A2 dispatch, decision L39: callers pass `entry.runtime_data.manager`, so lane 6 needs no manager and no runtime data field that lane 5 adds). Landed in lane 6: `MaintenanceTarget` is `store` (property), `async_delete_routine(device_id)`, `async_rebuild_index(*, dry_run) -> list[str]`, `async_refresh_summaries(*, dry_run) -> list[str]`, `async_blueprint_reinstalled()`; maintenance owns the D28 rule (`cleanup_candidates`, `due_for_cleanup`, `next_cleanup_at`, `async_clean_up`) and `shipped_blueprint_text()`, `blueprint_hash(text)` |
| `health.py` | `async_collect(hass, version, manager)` adds `blueprint_schema`, `blueprint_status`, `owned_count`, `loaded_count`, `issues`, `last_reconcile`; `degraded` on a modified blueprint, a failed automation load or an adapter fallback; `error` when the adapter is incompatible |
| `websocket_api.py` (new) | TECH\_SPEC 4.7 as written; `async_register(hass)` from `async_setup_entry` |
| `services.py` (new) | `async_setup_services(hass)` called from `async_setup` (quality rule `action-setup`); one handler per action, each a one line call into the manager of the loaded entry |
| `trigger.py`, `condition.py` (new) | the core integration platform shape proven in V13 (`async_get_triggers`, `async_get_conditions`, `triggers.yaml`, `conditions.yaml`); keys `action_skipped`, `paused`, `resumed`, `is_paused`, `is_active` |
| `repairs.py` | issue ids as TECH\_SPEC 4.8; `async_create_fix_flow(hass, issue_id, data)`; `async_sync_issue(hass, issue_id, present: bool, placeholders)`. Seeded on `dev` before lane 5 (decision L41): the catalog constants, `CATALOG`, `FIXABLE`, `issue_registry_id(issue_id, subject=None)` and `async_sync_issue(hass, issue_id, present, placeholders=None, *, subject=None)`, where a per routine issue passes the automation id as `subject` (registry id `<issue>_<subject>`, data `{issue_id, subject}`), plus a title and description per catalog issue in `strings.json`; lane 11 adds the fix flows and turns each fixable issue's `description` into its `fix_flow` strings |
| Entities (`entity.py`) | Landed in lane 8 (`c228ea1`, L52): the two time entities take the profile's label as translation key (`turn_on_at`, `start_at`, `open_at`, `lock_at`, ...), unique ids keep `on_time` and `off_time`; `reason` is a capability attribute; `manager.page_keys(device_id)` names each device's controls; `unavailable_reason(device_id, key)` makes only config controls unavailable on an incompatible adapter. The manager pre registers `device_routines_<device id>_manual_override` (switch) and `device_routines_<device id>_paused_until` (datetime) at opt in, so their entity ids exist at the first write; lane 8 claims them and replaces the test shim of `tests/integration/conftest.py` (L44). `DeviceRoutinesDeviceEntity(manager, device_id, key)` base: unique id `device_routines_<device id>_<key>`, `linked_device_info` (L25), translation key equals the key, `available` false with a `reason` attribute per TECH\_SPEC 4.5; every platform sets `PARALLEL_UPDATES = 0` |

Blueprint inputs: exactly the TECH\_SPEC 5.2 table (29 inputs), keys in that order; `extra_conditions` included. Value types (pinned at the wave A1 dispatch, shared by `compiler.compile` and the blueprint's selectors): times as `HH:MM:SS` strings; `days_start` and `days_end` as lists of `Weekday` values in Monday to Sunday order; durations and minutes as `int`; flags as `bool`; entity ids and service names as `str`, with the sentinels for every unused helper; `extra_conditions` as a list of condition mappings (empty by default). Triggers, conditions and branches as TECH\_SPEC 5.3 to 5.5 with L20, L22 and the A6 note applied.

Store keys: TECH\_SPEC 6.

### 4.3 Wave A1: four independent lanes

Dispatch together. None of them imports another's new module; each tests against the contract.

#### Lane 1: pure core (compiler, markers, skip target)

Files: create `custom_components/device_routines/compiler.py`, `tests/unit/test_compiler.py`; extend `custom_components/device_routines/markers.py` and `tests/unit/test_markers.py` (seeded with M1 and M2, decision L34; keep the seeded names and tests); create `tests/unit/strategies.py` (hypothesis strategies for `RoutineSettings` per domain profile, reused by lanes 2 and 5); modify `models.py` (`RoutineView`), `nextrun.py` (`skip_target`), `sentences/en.json` (the Section 4.2 phrases), `tests/unit/test_nextrun.py`, `tests/unit/test_sentence.py`.

- [ ] Write the failing tests: `test_compile_then_decompile_is_identity` (hypothesis, every valid settings for every profile); `test_decompile_then_compile_is_identity` (over `compile` outputs); `test_compile_never_emits_a_refused_action` (hypothesis: no `on_action` of `lock.unlock`, `cover.open_cover` on garage, gate and door classes, `valve.open_valve` on gas, `alarm_control_panel.*`); one test per `validate` rejection of TECH\_SPEC 3.3 asserting the problem key; `test_days_end_shifts_by_one_when_crossing_midnight`; `test_late_window_end_wraps_at_midnight`; `test_disabled_inputs_carry_sentinels`; `test_is_valid_shape_rejects_unknown_missing_and_mistyped_keys`; `test_input_keys_order_is_fixed`; `test_automation_id_is_stable_and_matches_m1`; `test_is_owned_needs_both_markers` (alias, label and category alike do not count); `test_alias_is_generated_follows_history`; `test_config_hash_ignores_id_and_key_order`; `test_helper_slug_avoids_collisions`; `test_skip_target_window_start_pairs_its_end` (D18); `test_skip_target_window_end_alone` (D19); `test_skip_target_running_countdown`; `test_skip_target_pressed_twice_extends`; `test_skip_target_equals_the_sentence_action` (hypothesis, TECH\_SPEC 11.5); `test_state_reads_skipped_paused_and_off_under_40_characters`.
- [ ] Run `pytest tests/unit -q`; expected: the new tests fail on import.
- [ ] Implement `compiler.py`, `markers.py`, the `nextrun` and `sentence` additions and `RoutineView` to the Section 4.2 contract; derived inputs per TECH\_SPEC 3.3.
- [ ] Run `pytest tests/unit tests/test_repository.py -q --cov`; expected: green, both new modules at 100 percent.
- [ ] Gates and commit: `feat(core): compiler, markers and skip targets (Build A lane 1)`.

#### Lane 2: blueprint and behavior matrix

Files: create `custom_components/device_routines/blueprints/device_routine.yaml`, `tests/blueprint/__init__.py`, `tests/blueprint/conftest.py`, `tests/blueprint/test_schema.py`, `tests/blueprint/test_windows.py` (B01 to B08, B19 to B22, B40 to B42), `tests/blueprint/test_durations.py` (B09 to B18), `tests/blueprint/test_pause_and_skip.py` (B27 to B36), `tests/blueprint/test_override.py` (B23 to B26), `tests/blueprint/test_pulse.py` (B37, B38), `tests/blueprint/test_refusals.py` (B39), `tests/blueprint/test_without_integration.py` (B43).

Interfaces: consumes the input key names and sentinels of Section 4.2 (hand written dicts in `conftest.py`, one factory `inputs(**overrides)`); produces the file and `tests/blueprint/conftest.py` fixtures `installed_blueprint`, `routine_automation(inputs)`, `sandbox_switch`, `routine_timer`, `routine_schedule`, `override_switch`, `paused_until`, `cold_start(restore_states)`, reused by lanes 5 and 14. Patterns to copy: `tests/stage0/test_v5_blueprint.py` (install through `DomainBlueprints.async_add_blueprint`), `test_v7_helpers.py` (helpers through the in process WebSocket dispatch), `test_v10_timer_restore.py` (cold start over a restore cache), `test_v12_datetime.py` (the `not_paused` template).

- [ ] Write the failing tests: `test_schema.py` (`test_loads_through_the_automation_blueprint_schema`, `test_every_input_of_the_contract_exists_once_in_order`, `test_no_source_url` (L24), `test_min_version_is_2026_10_2`, `test_every_trigger_condition_and_branch_has_an_alias`, `test_mode_queued_max_10`, `test_no_schedule_block_started_trigger` (A6), `test_timer_done_has_the_caught_up_event_twin` (L20), `test_not_paused_is_the_only_template` (L22)); one test per behavior matrix row named `test_bNN_<short name>` asserting the device state and the timer state at each step of TECH\_SPEC 11.2, with time travel (`async_fire_time_changed`) and, for B11, B17, B38 and B41, a cold start over restore state.
- [ ] Run `pytest tests/blueprint -q`; expected: fail on the missing file.
- [ ] Write the blueprint to TECH\_SPEC 5 with the Stage 0 results applied (L20 second `timer_done` trigger on `device_routines_timer_caught_up` filtered by `device_id`; L22 `not_paused` template, no `pause_ended`; state triggers for `block_on` and `block_off`, never `schedule.block_started`; sentinel entities; `enabled: !input` on time triggers and on the extra conditions; `alias` on every trigger, condition and branch; the `device_routines_action_skipped` event with `device_id`, `automation_id`, `trigger_id`, `action`, `scheduled_at`).
- [ ] Run `pytest tests/blueprint -q`; expected: every row green; `pytest tests/stage0 -q` still green.
- [ ] Gates and commit: `feat(blueprint): device routine blueprint schema 1 with the behavior matrix (Build A lane 2)`.

#### Lane 3: adapter write capabilities

Files: modify `custom_components/device_routines/ha_adapter.py`; create `tests/integration/test_adapter.py`; modify `tests/test_repository.py` only if a new public core prefix is needed (none expected: the adapter may import anything).

Interfaces: produces the `ha_adapter` contract of Section 4.2; consumes `markers.is_owned`, `markers.has_routine_id` and `markers.BLUEPRINT_PATH`, already on `dev` (decision L34), so the write guard and `is_detached` use the real predicates and no stub is needed.

- [ ] Write the failing tests: `test_write_creates_updates_and_deletes_an_entry_with_a_run_in_flight_elsewhere` (after `tests/stage0/test_v6_write_path.py`); `test_write_refuses_an_unowned_config` (same alias, label and category, no M1 or M2: `NotOwnedError`, file untouched); `test_write_keeps_the_other_entries_semantically` (values and key order of every other entry equal before and after); `test_write_retries_once_then_raises_write_conflict`; `test_delete_removes_the_registry_entry`; `test_install_blueprint_is_usable_at_once_and_hash_matches`; `test_system_user_is_created_once_and_is_an_administrator`; `test_create_update_delete_timer_and_schedule_with_chosen_id_and_label`; `test_a_non_admin_system_user_is_refused`; `test_missed_timer_finishes_reads_restore_state` (active with `finishes_at` in the past is reported, time left is not); `test_ensure_label_and_category_are_idempotent`; `test_is_detached`; `test_check_reports_each_capability_and_logs_once` (monkeypatch a missing helper: WARNING once, then INFO once on recovery, F5).
- [ ] Run `pytest tests/integration/test_adapter.py -q`; expected: fail on missing functions.
- [ ] Implement to the contract; the write path replicates the editor (TECH\_SPEC 4.2 write row) with the adapter's own `asyncio.Lock` and the file hash compare; helpers through the in process `ActiveConnection` dispatch (L23).
- [ ] Run `pytest tests/integration/test_adapter.py tests/test_repository.py -q --cov`; expected: green.
- [ ] Gates and commit: `feat(adapter): write, blueprint, helper, label and restore state capabilities (Build A lane 3)`.

#### Lane 4: attribution

Files: create `custom_components/device_routines/attribution.py`, `tests/integration/test_attribution.py`; fixtures `tests/fixtures/attribution/v3_time_triggered.json` (exists) and a new synthetic `tests/fixtures/attribution/synthetic_contexts.json` (an app change with `user_id`, a wall switch change with a bare context, a script started run and its state change).

Interfaces: produces the `attribution` contract; consumes nothing (the tests implement `RoutineLookup` and `OverrideSink` as fakes).

- [ ] Write the failing tests: `test_b44_time_triggered_automation_change_is_automation` (replays the V3 fixture); `test_b45_wall_switch_change_is_device`; `test_b46_app_change_is_user`; `test_script_started_contexts_count_as_automation`; `test_parent_id_in_the_map_counts`; `test_map_is_capped_and_expires` (10,001 entries, 24 hours); `test_first_30_seconds_only_fill_the_map`; `test_manual_change_away_from_expected_sets_override`; `test_manual_change_back_to_expected_clears_override`; `test_no_override_while_paused` (D21); `test_no_override_with_respect_manual_off`; `test_no_override_when_routine_inactive`; `test_only_watched_entities_are_classified`.
- [ ] Run; expected: fail on import.
- [ ] Implement `Attributor` to TECH\_SPEC 4.3 and the contract.
- [ ] Run with coverage; expected: green, 100 percent.
- [ ] Gates and commit: `feat(attribution): manual change attributor with the V3 replay (Build A lane 4)`.

### 4.4 Wave A2: the service layer

Three lanes. Lane 5 is the critical path; lanes 6 and 7 are small and finish first.

#### Lane 5: RoutineManager

Files: create `custom_components/device_routines/manager.py`, `tests/integration/test_manager.py`, `tests/integration/test_sync_back.py`, `tests/integration/test_reconcile.py`, `tests/integration/conftest.py` additions (a `manager` fixture over a loaded entry with the Section 4.3 fixtures); modify `__init__.py` (build the store, the manager and the attributor in `async_setup_entry`; reconcile after the started event; `async_remove_entry` delegating to the manager), `const.py` (`PLATFORMS` grows in wave A3; the manager does not need it).

Interfaces: consumes lanes 1 to 4 and lanes 6 and 7; produces the `manager` contract.

- [ ] Write the failing tests, each named for the PRD row it proves: opt in through the label and through `async_opt_in` are equivalent and idempotent; opt out turns the routine off, removes the entities and records `opted_out_at`; the first setting creates the automation in `automations.yaml` with M1 to M8 and the helpers it needs; five settings inside one second produce one write (debounce); an invalid patch reverts the entity and returns the problem; `last_hash` and `last_valid_inputs` are recorded; a target entity rename rewrites the input and reloads; a device rename follows the alias only while it is still generated; a device removal turns the routine off and cleanup after `cleanup_after_days` deletes the automation and helpers (time travel, 0 disables); deleting the `Routines` label registry entry does not opt anyone out: the label is recreated and re applied from `opted_in`; a lookalike automation is never written and never listed as a routine (S7); two devices with the same name get distinct automation ids and helper ids; a pause schedules a resume at the stored time (L22) and resume applies catch up (D20); skip next sets `paused_until` from `nextrun.skip_target`; `missed_timer_finishes` after the started event fires `EVENT_TIMER_CAUGHT_UP` once per timer; `async_add_listener` receives `routine_changed` on every change and `EVENT_ACTION_SKIPPED` is re emitted.
- [ ] `test_sync_back.py`: a form edit with a hash the manager did not write updates the entities; an edit into an invalid shape turns the routine off, overwrites nothing and raises `invalid_inputs`; a refused action does the same; take control makes the routine `detached`, the entities unavailable with reason `detached` and raises `detached_routine`; a deleted automation resets the settings and keeps the device opted in; a restore of `automations.yaml` from git rebuilds the index from the markers and the entities follow.
- [ ] `test_reconcile.py`: every TECH\_SPEC 7 step idempotent; blueprint missing installs, modified raises `blueprint_modified` and leaves the file alone, a previously shipped version upgrades; a missing timer or schedule helper is recreated with the same entity id, a schedule raising `schedule_blocks_needed`; an owned automation that fails to load is regenerated once, then `automation_load_failed`; a missing target gives `missing_target` and the routine off; the area follows when `assign_area` is on (M9).
- [ ] Run; expected: fail on import.
- [ ] Implement `RoutineManager` to TECH\_SPEC 4.1 and 7, the write algorithm of 4.1, the event reactions of 7, and the `__init__.py` wiring.
- [ ] Run the three files with coverage; expected: green, `manager.py` at 100 percent.
- [ ] Gates and commit: `feat(manager): RoutineManager with sync back, reconcile and cleanup (Build A lane 5)`.

#### Lane 6: Store, migrations and maintenance

Files: create `store.py`, `migration.py`, `maintenance.py`, `tests/integration/test_store.py`, `tests/integration/test_migration.py`, `tests/integration/test_maintenance.py`; modify `settings.py` (every PRD 10.4 key, `OPTIONS_VERSION = 2`, `migrate`), `tests/unit/test_domains_settings_conflicts.py`, `config_flow.py` (the entry's `MINOR_VERSION` only) and `__init__.py` (export `async_migrate_entry` only; lane 5 owns the rest of the file).

- [ ] Write the failing tests: the Store round trips every key; `migrate_store` from a hand written version 0 payload; an unknown future version is refused; `settings.migrate` from version 1 options adds every new key at its default and keeps the two old ones; `async_migrate_entry` migrates options; `async_migrate_blueprint_schema` rewrites every owned automation from a fake schema 0 (decompile with the old rules, compile with the new, write, reload), keeps `previous_inputs`, continues past one failure and returns its id; every maintenance action is idempotent and `dry_run` changes nothing while reporting what it would.
- [ ] Run; expected: fail on import.
- [ ] Implement to the contract (the blueprint schema migration calls the manager through a small `Protocol` so lane 6 does not import lane 5).
- [ ] Run with coverage; expected: green.
- [ ] Gates and commit: `feat(store): Store schema 1, migrations and maintenance actions (Build A lane 6)`.

#### Lane 7: Schedule summary with routines

Files: modify `summary.py`, `sensor.py` (the Schedule sensor reads `paused_until` and `skipped_action`; routines sort first), `tests/integration/test_summary.py`.

- [ ] Write the failing tests: with a fake `RoutineItemsProvider`, the routine item sorts above automation items; the state reads `Skipped, on Thu 5:00 PM`, `Paused until Sun 6:00 PM` and `Routine off` as FR-S4 asks, under 40 characters; hand written lines are unchanged by a pause; `async_refresh_device` recomputes one device without rebuilding the index; a detached routine reads as `kind: detached_routine` through the parser.
- [ ] Run; expected: fail.
- [ ] Implement.
- [ ] Run `pytest tests/integration/test_summary.py tests/golden -q`; expected: green, the golden corpus unchanged.
- [ ] Gates and commit: `feat(summary): routine items, paused and skipped states (Build A lane 7)`.

### 4.5 Wave A3: platforms, surfaces and features

Eight lanes, all against the manager contract (the manager exists after wave A2, so these tests run against the real manager through the `manager` fixture; a lane that needs a manager behavior that is missing reports it instead of adding it to a platform file, rule P16).

Shared module arbitration for this wave (decision L45): `config_flow.py` code is lane 10's, and lane 14 writes the AI disclosure only as the `ai_task_entity` description in `strings.json`; `manager.py` takes lane 14's weekly schedule lifecycle and lane 8's one additive change (`unavailable_reason(device_id, key=None)`, so the time entities can read `weekly_schedule` once lane 14 fills it); `summary.py` takes additive, separate functions from lanes 11 (the `conflict` issue sync), 12 (the day's schedule for `schedule/today`) and 14 (the AI queue); `__init__.py` takes additive lines from lanes 9 (services in `async_setup`), 10 (`async_remove_entry`), 12 (WebSocket registration) and 15 (Health from `manager.health_inputs()`); `ha_adapter.py` takes lane 10's two removal capabilities and lane 14's schedule block read. The orchestrator rebases in landing order and resolves the overlaps.

#### Lane 8: device page platforms and the hub button

Files: create `switch.py`, `time.py`, `select.py`, `number.py`, `button.py`, `datetime.py`, `tests/integration/test_platforms.py`; modify `tests/integration/conftest.py` (drop the lane 5 shim: `ShimOverride`, `ShimPausedUntil`, the mocked platform and the `PLATFORMS` patch of the `routines` fixture), `entity.py` (`DeviceRoutinesDeviceEntity`), `const.py` (`PLATFORMS`), `strings.json`, `translations/en.json`, `icons.json`, `tests/test_repository.py` (add `datetime` to the platforms whose keys are collected).

- [ ] Write the failing tests: per domain profile the exact entity set of TECH\_SPEC 4.5 (no `on_time` for `media_player` and `lock`, `turn_off_after` only where the option exists, `target` only with several candidates); categories and `entity_registry_enabled_default` as the table; `turn_back_on_after` created disabled and inert until a value is set; every write goes through `manager.async_update` with the right patch (patch the method, assert the call); `routine` switch mirrors the automation both ways; `skip_next` unavailable when nothing is scheduled; `resume` unavailable unless paused or skipping; `paused_until` rejects a past value with a translated error; `manual_override` turned off by a person calls `async_resume` style catch up; availability reasons `adapter_incompatible`, `detached`, `missing_target`; entities removed from the registry on opt out; the hub `cleanup_now` button calls maintenance; `PARALLEL_UPDATES = 0` on every platform module (an AST test).
- [ ] Run; fail. Implement. Run with coverage; green. Gates and commit: `feat(platforms): routine controls on the device page (Build A lane 8)`.

#### Lane 9: actions

Files: create `services.py`, `services.yaml`, `tests/integration/test_services.py`; modify `__init__.py` (`async_setup_services` from `async_setup`), `strings.json`, `translations/en.json`.

- [ ] Tests: `skip_next`, `pause` (`until` or `for`, exactly one), `resume`, `enable`, `disable` and `maintenance` with device, area, label and entity targets; the ignored list names each target without a routine with its reason (S13); no matching target raises `ServiceValidationError` with key `no_routine_targets`; responses carry the TECH\_SPEC 4.6 fields; hassfest's services schema check passes locally (`python -m script.hassfest` is CI's; here, a test loads `services.yaml` and asserts every action and field has a `strings.json` entry).
- [ ] Run; fail. Implement. Run; green. Gates and commit: `feat(actions): skip, pause, resume, enable, disable and maintenance (Build A lane 9)`.

#### Lane 10: config flow, options and removal

Files: modify `config_flow.py`, `tests/integration/test_config_flow.py`; `__init__.py` (`async_remove_entry`); `ha_adapter.py` and `tests/integration/test_adapter.py` for the two removal capabilities of Section 4.2 (decision L37), additively.

- [ ] Tests: the `suggestions` step lists the devices the summary flagged, all unchecked, skippable, and opts the selected ones in; the options `devices` picker is filtered to eligible devices and prefilled; `suggestions` repeatable in options; every PRD 10.4 setting on the `settings` page with validation errors translated; `on_removal` keep takes control of every owned automation with the `formerly_managed` description and removes the blueprint when nothing uses it (S8 in the harness); delete removes owned automations and their helpers; the system user is removed with the entry (L23).
- [ ] Run; fail. Implement. Run; green. Gates and commit: `feat(flow): suggestions, the devices picker and removal (Build A lane 10)`.

#### Lane 11: Repairs catalog and the Problem sensor

Files: modify `repairs.py`, `binary_sensor.py`, `strings.json`, `translations/en.json`; create `tests/integration/test_repairs.py`.

- [ ] Tests: each issue of TECH\_SPEC 4.8 raised in its situation and cleared when it ends; each fix flow does exactly its one step (`blueprint_modified` reinstalls and reloads, `invalid_inputs` restores `last_valid_inputs`, `detached_routine` creates a new routine and never touches the detached automation, `write_conflict` retries, `automation_load_failed` regenerates); `schedule_blocks_needed` and `adapter_incompatible` are not fixable and carry their links; `conflict` only while `raise_conflict_repairs` is on and only for a routine against another automation at the same minute (FR-S6); the Problem sensor is on while any issue is open and lists the ids.
- [ ] Run; fail. Implement. Run; green. Gates and commit: `feat(repairs): the Repairs catalog with fix flows (Build A lane 11)`.

#### Lane 12: WebSocket API

Files: create `websocket_api.py`, `docs/api.md`, `tests/integration/test_websocket_api.py`; modify `__init__.py` (register), `tests/test_repository.py` (allow `homeassistant.components.websocket_api`).

- [ ] Tests, through `hass_ws_client`: every command of TECH\_SPEC 4.7 returns the same payload as the manager's own result (`routines/list`, `get`, `set` valid and invalid, `action` for each action with each target kind, `devices/opt` for each op, `schedule/today`, `settings/get` and `set`, `maintenance` with `dry_run`); writing commands refuse a non admin; `subscribe` pushes `routine_changed`, `schedule_changed`, `settings_changed` and `health_changed` on the matching events and stops on unsubscribe; datetimes serialize as ISO strings.
- [ ] Run; fail. Implement. Run; green. Write `docs/api.md` from the tests (one section per command with request and response examples using generic names). Gates and commit: `feat(websocket): the console contract (Build A lane 12)`.

#### Lane 13: integration triggers and conditions (FR-R17)

Files: create `trigger.py`, `condition.py`, `triggers.yaml`, `conditions.yaml`, `tests/integration/test_triggers_conditions.py`; modify `strings.json`, `translations/en.json`. Pattern: `tests/fixtures/stage0/custom_components/stage0_probe/` and `tests/stage0/test_v13_triggers.py`.

- [ ] Tests: `action_skipped`, `paused` and `resumed` fire on the manager's bus events with device, area and label targets and `behavior` each, first and all; `is_paused` and `is_active` with `any` and `all`; the descriptions carry the target selector the editor's pickers need; a target with no routine never fires.
- [ ] Run; fail. Implement. Run; green. Gates and commit: `feat(triggers): purpose specific triggers and conditions (Build A lane 13)`.

#### Lane 14: Phase 3 features in the manager and summary

Files: create `ai_prompt.py`, `tests/integration/test_ai_path.py`, `tests/integration/test_weekly_schedule.py`, `tests/integration/test_hub_routines.py`; modify `nextrun.py` and `tests/unit/test_nextrun.py` (Skip next outside a weekly schedule block, decision L38: the manager reads the helper's blocks through the adapter's `schedule/list` dispatch and passes the next block's start and end to `skip_target`, which skips the start with its end as D18 does for a window); modify `summary.py` (the AI queue of TECH\_SPEC 4.4), `manager.py` (weekly schedule helper lifecycle; keep alive and pulse are compiler and blueprint work already landed; the late start window default from `default_late_start_window_min`), `sensor.py` (hub Routines attributes complete), `config_flow.py` (the AI options text: exactly what is sent and where).

- [ ] Tests: Days set to Weekly schedule creates `schedule.routine_<slug>` named `<device name> routine` with the label, links it, and makes the two time entities unavailable with reason `weekly_schedule`; a recreated empty schedule raises `schedule_blocks_needed`; the AI path with a fake AI Task entity: only lines the parser could not read are sent, as trigger, condition and action blocks with entity ids only, one automation at a time; the token bucket at `ai_calls_per_hour`; the cache by config hash in the Store; nothing during the first five minutes after start; the `(AI)` suffix and `source: ai`; off by default; the hub Routines sensor lists every managed routine with `device`, `area`, `summary`, `next_action`, `status` and `automation`.
- [ ] Run; fail. Implement. Run; green. Gates and commit: `feat(phase3): weekly schedule helpers, the AI path and the hub Routines attributes (Build A lane 14)`.

#### Lane 15: docs, quality scale, Health and diagnostics

Files: modify `docs/user-guide.md` (sections: Giving a device a routine; Skip, pause and resume; What the managed automation looks like; If you edit the automation yourself; Removing the integration; Weekly schedules; Turn back on after; Pulse; Only when the integration is off (the L20 timer note and L21 DST nights); Dashboards and scripts with the actions, triggers, conditions and a markdown card over the Routines sensor; Supported devices (PRD 5.3); Troubleshooting (the Repairs catalog); Limitations), `README.md` (status, features, FAQ, a privacy statement), `quality_scale.yaml` (F1 plus every rule Build A satisfies), `docs/TECH_SPEC.md` and `docs/PRD.md` notes (F6), `health.py`, `diagnostics.py`, `tests/integration/test_health.py`, `tests/integration/test_diagnostics.py`.

- [ ] Tests: Health `degraded` and `error` rules and every new attribute; diagnostics report the Store as counts and owned records as shapes with ids, names and aliases redacted.
- [ ] Write the guide sections with generic names only (a living room fan, a robot vacuum); every example a routine the harness tests actually run.
- [ ] Run `pytest tests/test_repository.py tests/integration/test_health.py tests/integration/test_diagnostics.py -q`, `python -m tools.style_check`, `python -m tools.privacy_check --staged`; green.
- [ ] Commit: `docs: user guide for routines, quality scale refresh, Health and diagnostics complete (Build A lane 15)`.

### 4.6 Wave A4: integration, the simulation and the exits

The orchestrator, with one lane for A4.2 if time allows. Amended at the wave A4 dispatch (decision L54): A4.0 to A4.3 run as four parallel lanes in their own worktrees (`lane/carryover`, `lane/contracts`, `lane/simulation`, `lane/golden`); A4.1 and A4.2 do not edit `manager.py` or the other service modules A4.0 owns: a defect they find is pinned as a strict `xfail` test, reported, and routed to the carry over lane or fixed by the orchestrator after A4.0 lands. A4.0 drops two items to Build B: Health's `degraded` on an adapter fallback (nothing to read until D2(b) exists) and the `automation_load_failed` fix for a schema migration failure (only reachable from schema 2); moving the removal logic into `maintenance.py` and `RoutineSummary.next_action` are optional. A4.4 and A4.5 are the orchestrator's.

- [ ] **A4.0 Carry overs from waves A1 to A3.** The manager remembers only in memory that it turned a routine off (invalid inputs, missing target), so after a restart a routine whose target returns stays off (L44): persist the reason in the Store (a minor version with its migration and test) or re derive it at reconcile; the optional `RoutineSummary.next_action` if the summary's decompile duplication bites (L43); from lane 9 (L46): `async_run_action` must reject a past `until` or a zero `for` before resolving targets (FR-R12; the strict xfail `test_a_pause_that_ends_now_or_in_the_past_is_rejected_with_a_translated_error` then passes and loses its marker), `resolve_targets` must map this integration's linked device records (L25) to the user's device, and maintenance must raise translated errors instead of a bare `AdapterError` (quality rule `action-exceptions`); action icons in `icons.json`; from lane 11 (L48): after `async_create_new_routine` the device's old `invalid` and `load_failed` flags linger until the next sync, and the `automation_load_failed` fix does nothing for a schema migration failure (only reachable from schema 2, Build B); from lane 12 (L49): an edit of a hand written automation pushes no `schedule_changed` to WebSocket subscribers (the summary should tell the manager after a view refresh, debounced); from lane 15 (L50): Health's `degraded` on an adapter fallback has nothing to read until the adapter reports fallbacks (D2(b) is not built); the remaining `<!-- A3: lane N -->` markers in `docs/user-guide.md` are checked against the landed tests and removed; from lane 10 (L51): the removal logic lives in `__init__.py` and could move into `maintenance.py`; from lane 8 (L52): the manager fires no event when a routine's timer starts or stops, so Skip next stays unavailable during a countdown of a routine without times (fix first: watch the timer helper and fire `routine_changed`); Turn back on after is not unavailable while a schedule says off (PRD 4.3, a key based rule in `unavailable_reason`); `missing_target` should leave the target select available so a person can pick another target; "Close after" and "Lock after" wording (PRD 5.3) needs a profile label for the duration; `manager.ENTITY_KEYS` and `const.ENTITY_PLATFORMS` list the keys twice; from lane 14 (L53): two mechanisms clear `schedule_blocks_needed` (lane 11's house wide `next_event` listener and lane 14's per routine block watcher over `schedule/list`): keep one; a second Skip next during a skipped weekly block reads `nothing_to_skip`, and the state reads "Paused until" instead of "Skipped, ..." for a skipped block; a pending delayed Store save of `ai_cache` is lost if the entry reloads within the one second delay (flush the Store on unload); after a device rename and a restart while Days is not Weekly schedule the old schedule helper can be left behind (still labeled); anything else found while integrating.

- [ ] **A4.1 Contract tests.** `tests/integration/test_contracts.py`: `compile()` output validates against the installed blueprint for every domain profile and option combination (hypothesis over `strategies.py`); every entity, action, WebSocket command and trigger reaches the manager and nothing else (an AST test that platform files call only `manager.*`, `maintenance.async_run` and base classes, rule P16); the round trip of PRD 12: for every valid settings, the Schedule sentence of the compiled routine equals the sentence generated from the settings.
- [ ] **A4.2 The 30 day simulation (G8).** `tests/integration/test_thirty_days.py`: one harness instance, time travel through 30 days with three routines (a window, a turn off after, a weekly schedule), a device rename on day 3, a target entity rename on day 7, `automations.yaml` restored from a copy on day 10, a blueprint schema upgrade from a fake version 0 on day 14, a device offline for day 20, a device removed on day 22 with cleanup at day 22 plus `cleanup_after_days`, two restarts (cold starts over restore state) on days 5 and 25; asserts: no Repairs issue outside `blueprint_modified`, `invalid_inputs` and `schedule_blocks_needed` (and none of those unless provoked), every scheduled action ran on time, the sentences were right at every check, the Store rebuilt equals the Store kept.
- [ ] **A4.3 G5 reconciliation (F3).** List the 11 unparsed corpus items with the construct that stops each; extend `parser_grammar` for every construct that reads with zero guessing (each with a unit test and the corpus diff reviewed line by line); if the corpus still parses under 90 percent, write a decision entry amending the G5 measure to count golden negatives separately, with the numbers, and owner log O14 for Jayant's veto.
- [ ] **A4.4 Whole suite.** `pytest -m "not live" --cov`; coverage at least 95 percent; `ruff`, `mypy`, hassfest and the HACS action in CI green; `CHANGELOG.md` complete under 0.3.0; `manifest.json` 0.3.0; `docs/validation/phase-2.md` and `phase-3.md` with the harness rows (one row per behavior matrix id, per integration test file, per acceptance scenario that runs in the harness: S6, S7, S8, S11, S12, S13 and the restart halves of S3, S4 and S5).
- [ ] **A4.5 Exit.** Adjust `release.yml` so a `-beta.N` suffix is stripped from the tag before the manifest version comparison (L33), with `tests/test_repository.py` asserting it. Fast forward `main`; tag `v0.3.0-beta.1`; `release.yml` builds the pre release; deploy it by hand (Section 0.1.6: `shell_command.deploy_device_routines` with `ref: v0.3.0-beta.1`, read the response, turn auto deploy back on); write the R1 request into the Status line and the owner log (O15), with the Section 8.1 owner session checklist; update this file's Status line; start Build B (Section 6) without waiting.

### 4.7 Tests summary

| Layer | Where | Rows |
| --- | --- | --- |
| Pure units | `tests/unit/` | compiler round trips and refusals, markers, skip targets, settings migration, the new sentence states |
| Blueprint behavior | `tests/blueprint/` | B01 to B43 |
| Attribution | `tests/integration/test_attribution.py` | B44 to B46 and the rules of TECH\_SPEC 4.3 |
| Integration | `tests/integration/` | every item of TECH\_SPEC 11.3 |
| Contracts and simulation | `tests/integration/test_contracts.py`, `test_thirty_days.py` | PRD 12 round trip, P16, G8 |
| Golden | `tests/golden/` | unchanged lines, plus the A4.3 grammar additions |

### 4.8 Exit criteria and release

Every task of Sections 4.3 to 4.6 done; the harness rows of `docs/validation/phase-2.md` and `phase-3.md` recorded; coverage at least 95 percent; CI green on `dev` and `main`; `v0.3.0-beta.1` released and deployed to the instance's disk; R1 requested. The full `v0.3.0` tag waits for Section 5.4 (L33: `v0.2.0` is skipped, because Phases 2 and 3 ship together).

### 4.9 Review focus

Inputs the spec implies but no row of TECH\_SPEC 11 names, most likely to bite first. Each has its test in the lane named.

1. A hand maintained `automations.yaml` with comments and anchors: the editor's write path re dumps the file and drops comments, and so does the adapter. Lane 3 asserts every other entry is kept semantically (values and key order) and lane 15 documents the limitation in the guide, the same one the automation editor has.
2. Deleting the `Routines` label from the label registry looks like every device opting out at once. Lane 5 asserts no routine turns off, the label is recreated and re applied from `opted_in`.
3. Two devices with the same name: the alias repeats (allowed), but the entity id and the helper ids must stay distinct. Lane 1 (`helper_slug`) and lane 5 (two same named devices) assert it.
4. `automations.yaml` restored from git while the Store still remembers a routine the file no longer holds, or holds with other inputs: lane 5 asserts the index is rebuilt from the markers and the entities follow the file, never the Store.
5. Two writes racing (a burst of settings during a form save): lane 3 asserts one retry on a moved hash, then `write_conflict`; lane 5 asserts a burst inside the debounce is one write and the entities end consistent.

## 5. Restart R1 and live validation A

R1 loads Build A. The session that runs this section is a live session (reads and writes over MCP, rule 2) and runs while Build B is open in another session; the two never touch the same files (Build B commits code, this section commits only `docs/validation/phase-2.md`, `phase-3.md`, the owner log and the Status line).

### 5.1 Before the restart

1. Confirm over MCP that the deployed commit (`shell_command.device_routines_deploy_status`) is the `v0.3.0-beta.1` commit and that the running commit (Health) is still `d00fa2f`.
2. Stage nothing on the sandbox device: no routine exists before the first load. Record the sandbox plug's state and its hand automation's state (both read only) as the baseline.
3. The owner session checklist (Section 8.1, session 1) is in the owner log: restart; then a few minutes in the UI; then operate four devices; then the token. The session asks for nothing else.

### 5.2 Restart bundles: what every restart carries

Every restart (R1, R2 and any the owner does for his own reasons) is announced before it happens. The live session stages scenarios according to the time of day of the restart, reads before, and reads after; none of these scenarios ever gets a restart of its own. Restart halves that remain unstaged when the project ends stand on their harness rows.

| Scenario | Stage before the restart (every step a write with a read before and after) | Read after the restart | When it fits |
| --- | --- | --- | --- |
| S3 (missed on time is caught up) | With the sandbox routine on a 17:00 to 09:00 window and the time inside the window: turn the routine off, turn the plug off over MCP, turn the routine back on (the manual off happened while the routine was off, so no override) | The plug on within 60 seconds of the Health sensor turning `ok`; the trace shows the `ha_start` branch | A restart inside the on period |
| S4 (manual on across a restart) | Time inside the off period: turn the plug on over MCP (a user context: Manual override turns on, `last_change_source: user`) | The plug still on after the restart with the override still on; at 17:00 the trace shows the override cleared and the on action a no op | A restart inside the off period, before 17:00 |
| S5 (countdown survives a restart) | Time inside the off period, together with S4: set Turn off after to 45 before turning the plug on; restart within 20 minutes | The plug turns off 45 minutes after the manual on, across the restart; the timer entity shows the remaining time after the restart | With S4 |
| S12 (pause survives a restart) | Time inside the off period: set the routine's on time to 10 minutes ahead, call `device_routines.pause` with `for` 20 minutes targeting the sandbox device's area, restart inside the pause | No turn on at the on time (the `action_skipped` event in the trace); the plug on at the pause end (D20); then set the on time back to 17:00 | A restart inside the off period when S4 and S5 are already recorded |
| C3 (blueprint form, Take control button) | nothing | The owner's look, recorded from his words | R1 |
| C5 (editor pickers) | nothing | The owner's look | R1 |

R1 carries nothing staged (first load). R2 carries S3 or S4 plus S5, by the clock. Any later restart carries what is left.

### 5.3 After the restart: live validation A

Order matters: the read only checks first, then the writes on the sandbox device, each with a read before and after, each recorded as a row of template 9.1 in `docs/validation/phase-2.md` or `phase-3.md`.

1. Health `ok` with `commit` equal to the beta tag's sha, `blueprint_status: ok`, `owned_count: 0`; the label, category and blueprint exist (reads); no Repairs issue; the Schedule sensors of Phase 1 unchanged in number; `pytest -m live` if `local/live.env` exists (O2), else the same checks over MCP.
2. The read only WebSocket commands over MCP (`ha_call_service` with `ws_command`): `device_routines/routines/list` (empty), `devices/opt` list and suggest, `settings/get`, `schedule/today`.
3. Turn the sandbox plug's hand written automation off (read before and after; it stays off from here on; the plug keeps its state).
4. S2: opt the sandbox device in (through the WebSocket `devices/opt` or the label), set Turn on at 17:00 and Turn off at 09:00, timed; read the new entry in `automations.yaml` through the adapter's view (`automation/config`) and assert M1 to M8; the Schedule sensor reads the right sentence for the current period; `owned_count: 1`; the hub Routines sensor lists it.
5. S6: change Turn off at through the blueprint form path (`blueprint/substitute` is not needed: write the entry over the config endpoint as the editor does, with one input changed) and read the device page entity following; then set a refused action in the entry (`on_action: lock.unlock` style) and read: routine off, `invalid_inputs` open, the entry untouched; then restore the value through the device page entity (a write) and read the issue cleared and the routine back on. The fix flow itself is proven in the harness (lane 11); clicking it live is part of the owner's look (O3), not a requirement.
6. S7: take control of the sandbox routine (as V8 did), read `detached_routine` and the entities unavailable with reason `detached`; create a new routine through the fix flow; create a lookalike automation (`stage_s7_lookalike`, same alias, label and category, acting on nothing) and assert the manager lists it as `automation`, never writes it; delete the lookalike and the detached automation (reads).
7. S11: at a time in the off period, Skip next; the sentence reads Skipped, on <next day> 5:00 PM; at 17:00 the plug stays off and the `action_skipped` event and the `device_routines.action_skipped` trigger fire (a throwaway automation `stage_s11_listener` writing a persistent notification, deleted afterwards); the next day's window runs normally (a read the next day, or the harness row stands).
8. S13: a throwaway label `stage_s13` on the sandbox device and one plain device the owner has not named (any device without a routine; read only choice, the label is the only write): `device_routines.skip_next` with the label target returns the plain device in `ignored`; the label is removed (reads).
9. S1: the Schedule sensor of a device a hand written weekday automation starts reads the next start with `kind: automation` (read only; such automations exist on the instance).
10. Keep alive (FR-R4): during the on period, set Turn back on after to 2 (Turn off after must be 0, D27), turn the plug off over MCP, read it back on after two minutes; reset to 0. Pulse (FR-R8): in the blueprint form path set a pulse at a time five minutes ahead for 2 minutes with the steady guard at 1; read off then on; clear it.
11. Weekly schedule (FR-R2): set Days to Weekly schedule; read the `schedule.routine_<slug>` helper created with the label and the two time entities unavailable; set Days back to Every day and read the helper kept (cleanup governs it).
12. Integration triggers and conditions in the editor pickers: owner look (O4); the live half of the trigger ran in S11.
13. End state: the sandbox routine on with the 17:00 to 09:00 window, the hand automation off, no `stage_` artifact left (a final read lists none).

Every write scenario that fails becomes a harness test first (rule 12), then a fix on `dev`, which lands on the instance's disk at the next deploy and runs after the next restart that happens anyway; the record says which rows wait.

### 5.4 Release v0.3.0

When every row of Section 5.3 that does not need a restart is recorded (passes, or fails with a harness test and a fix in flight), tag `v0.3.0` on the commit that holds the record (after its CI passes), fast forward `main`, and move the instance to the tag through the deploy shell command. The rows of Section 5.2 that still wait for a restart are listed in the record and in the owner log; they do not hold the tag.

### 5.5 Resume

A session that starts right after R1 reads the Status line (which says: deployed `v0.3.0-beta.1`, running `d00fa2f` until the restart), confirms Health, and runs Section 5.3 from step 1. The prompt is Section 8.3.

## 6. Build B: Phase 4, restart R2, live validation B, publication

Goal: FR-R9, FR-R10 and FR-M1; the console with its Routines, Today and Settings views; the brands pull request and the HACS default submission prepared; release v1.0.0.

### 6.1 Scope and decisions to record when the build starts

- FR-R9 Only when: the `extra_conditions` input already round trips; Build B adds the user guide section, the Today view's condition flag and a harness row where a condition blocks a scheduled action (the Schedule line reads "(if 1 condition passes)").
- FR-R10 Sun relative times: blueprint schema 2 with `on_kind`, `off_kind` (select: time, sunrise, sunset) and `on_sun_offset`, `off_sun_offset` (text `HH:MM:SS`, optionally negative) inputs, two sun triggers per side enabled by compiler derived booleans, and `expected_on` for sun bounds built from the `sun` condition for the sun bound and the time condition for the fixed bound; a window bounded by sunset and sunrise uses the state of `sun.sun` (below horizon), never `after: sunset, before: sunrise`, which is never true on one calendar day. The compiler bumps `BLUEPRINT_SCHEMA_VERSION` to 2 and `decompile` reads both schemas; `async_migrate_blueprint_schema` rewrites every owned automation at the first load, which is the real exercise of A4.2's machinery. The companion `on_kind`, `off_kind` selects and the two offset numbers are advanced entities, disabled by default. `nextrun` takes the sun times from `Lookups` as the parser already does.
- FR-M1 Conversion offers: a pure `conversion.py` (added to the pure module list) with `match(lines: Sequence[ParsedLine], device: DeviceContext) -> RoutineSettings | None` for exact matches only: two time triggers turning one entity on and off with an optional weekday condition (FR-R1), a state on trigger with `for` and an off action (FR-R3); partial matches, seconds, templates and anything with a second device return None. Behind `offer_conversions`; a device that already has a routine gets no offer. The two step Repairs flow shows both sentences; confirming creates the routine, turns the original off and adds the `Replaced by routine` label (M6 is never added to it). The original is never edited beyond that.
- Console: `frontend/` with Lit and TypeScript, Vite into one bundle, vitest; `panel.py` registers `panel_custom` with `require_admin: true` through `homeassistant.components.panel_custom` and serves the bundle through `homeassistant.components.http.StaticPathConfig` (both added to the allowed public prefixes, F9); cache busting by version. Decision to record when reached: the built bundle `custom_components/device_routines/frontend/dist/` is committed, because the dev channel deploys the commit archive and the Home Assistant container has no node; a CI job `frontend` runs `npm ci`, vitest and the build and fails if the committed bundle differs from a fresh build; `frontend` joins the required checks (branch protection through `gh api`, `tests/test_repository.py` `REQUIRED_CHECKS`).

### 6.2 Lanes

Wave B1 (parallel): lane 16 pure (`conversion.py`, compiler schema 2, `nextrun` sun windows, strategies extended, unit tests); lane 17 blueprint schema 2 (the sun triggers and conditions, rows B47 sun window on and off, B48 sunset to sunrise window across midnight, B49 FR-R9 condition blocks a scheduled action and fires nothing, B50 schema 1 to 2 migration leaves every routine running); lane 18 console scaffold (`frontend/` tooling, the three views against a recorded `docs/api.md` fixture, vitest).

Wave B2 (after B1): lane 19 manager and platforms for FR-R10 (the companion entities, the migration at first load, Repairs rows); lane 20 conversion offers (summary flags candidates, the two step fix flow, the label, `offer_conversions`, tests with the golden corpus: exactly the automations that are exact matches are offered, counted and named in the test by their fixture number, never a partial one); lane 21 the console against the real WebSocket API in the harness (a Python test that serves the bundle and calls every view's commands), `panel.py`, the `frontend` CI job, `release.yml` already builds when `frontend/package.json` exists.

Wave B3 (orchestrator): brand assets final (`brand/icon.png` 256 and 512, `logo.png`, the `home-assistant/brands` layout under `brand/brands/`), the pull request text and the HACS default submission text prepared in `docs/publication.md` (not opened: O10, O11); `quality_scale.yaml` final with every rule done or exempt; README and the user guide complete (install, features, FAQ, privacy statement, every feature section); `CHANGELOG.md` 1.0.0; `manifest.json` 1.0.0; the whole suite; `docs/validation/phase-4.md` harness rows; fast forward `main`; tag `v1.0.0-beta.1`; deploy by hand; write the R2 request with the staged scenarios of Section 5.2 by the clock.

### 6.3 Restart R2 and live validation B

Before: stage S3 or S4 plus S5 from Section 5.2 by the time of day. After:

1. Health `ok` on the beta commit, `blueprint_schema: 2`, the sandbox routine migrated and running (its entry shows schema 2 inputs; the sentence unchanged).
2. The staged restart scenario rows.
3. S9 on the sandbox device, with no new approval: opt the sandbox device out, press Clean up now (its routine and helpers go), turn the hand written automation back on (read), and read the `conversion_offer` issue naming it with both sentences; confirm; read the new routine with M1 to M8, the original off with the `Replaced by routine` label, and the Schedule sensor listing the routine first and the replaced automation as a disabled line.
4. FR-R10 on the sandbox routine: set Turn on at to sunset with an offset of 30 minutes; read the entry, the sentence ("On 30 min after sunset" or the phrase table's wording) and, the same evening, the trace.
5. The console: the session reads the panel registration and fetches the bundle over the instance's HTTP (read only); the owner's walkthrough is O12.
6. End state as Section 5.3 step 13, with the routine on and the hand automation off and labeled.

### 6.4 Publication and v1.0.0

- `v1.0.0` is tagged when live validation B is recorded and the owner's console look (O12) is done; O12 is the only owner item that gates a release, because the console is the one surface the harness cannot judge.
- The brands pull request (O10) and the HACS default submission (O11) are opened by the session on the owner's go ahead; their texts and assets are ready in the repository from wave B3. When the brands pull request merges, the HACS job drops `ignore: brands` (L14).
- The channel switch (O13) is the owner's: install through HACS, turn auto deploy off, remove the package and the deploy tool; the deploy tool then reports `hacs_managed`. R3 is that restart. Until then the instance stays on the dev channel.
- Remaining restart scenario rows (Section 5.2) ride on the next restart the owner does for his own reasons.

## 7. Ongoing operations

- After every monthly Home Assistant release: run the CI matrix against the new core (the continue on error job becomes required once it passes), ask Jayant to update, and treat his update restart as a restart bundle (Section 5.2): stage the pending scenarios before it, run `pytest -m live` or the MCP reads after it, and bump the minimum version within the D14 rule.
- Dependabot pull requests monthly; merge on green.
- Watch the Home Assistant release notes for native device scheduling (PRD R9).
- Issues: triage with the templates; reproduce in the harness; every fix ships with a regression test.
- Parity: a change to `tools/ha_deploy.py` lands in both repositories in the same week; the CI parity job keeps that honest once the sibling pull request (O6) is merged.
- Between a deploy and its restart: do not open the diagnostics, Repairs fixes or options of Device Routines on the instance (Section 0.1.6).

## 8. Handoff

### 8.1 For Jayant: two owner sessions and the owner log

Everything that needs you is in `docs/owner-log.md`, grouped into two sittings. Nothing in a build waits for you; the live validation of a build waits only for the restart.

Owner session 1 (at R1, about thirty minutes, after Build A's exit is in the Status line):

1. Restart Home Assistant (the deploy of `v0.3.0-beta.1` is already on disk; the notification names it). Do not open Device Routines diagnostics, Repairs or options before the restart.
2. Tell the live session the restart is done (or just start a session with the Section 8.3 prompt).
3. In the UI, once the session says the sandbox routine exists: open its automation and look at the blueprint form (sections, the condition selector) and the Take control button without pressing it (O3); open the automation editor's trigger and condition pickers and look for the Device Routines entries with device, area and label targets (O4). Say what you saw in chat.
4. Operate the four devices you choose, one each on Z-Wave, Zigbee, Matter and Wi-Fi, by hand, by app and by voice, and run one script, while the session records (O1). Name the devices in chat only.
5. Create a long lived access token and write `local/live.env` (`HA_URL=...`, `HA_TOKEN=...`) on this machine (O2). Never paste the token in chat.

Owner session 2 (at R2, about fifteen minutes): restart (after the session has staged the scenario of the hour); walk through the console's three views (O12); decide O10, O11 and O13.

Anything else in the log is a decision with a default already applied; answer it whenever you like, in chat, by its id.

### 8.2 Kickoff prompt for the Build A session

```text
Continue Device Routines in /Users/jayant/agents/deviceroutines. I am Jayant, the owner.

Read, in this order: the Status line and Sections 0, 0.1, 3.1 and 4 of docs/IMPLEMENTATION_PLAN.md; docs/decisions-log.md from L26 to the end; docs/owner-log.md; docs/TECH_SPEC.md Sections 3 to 7; docs/stage0-report.md Sections V3, V5 to V9 and V13; then CLAUDE.local.md (private; never commit, quote or copy it).

Rules that override everything else: never restart Home Assistant or reload the config entry; live writes are pre approved with a read before and after (L26); nothing private in any commit, fixture, test, doc or message; no em dash character; conventional commits; ruff and mypy --strict clean; coverage at least 95 percent; tests in the same commit as the code; quality_scale.yaml, the user guide, README and CHANGELOG in the same commit as the behavior.

You are the orchestrator of Build A (plan Section 4): Phases 2 and 3 built together in the harness, with no restart until the build exit. Work the waves in order. For each wave, dispatch every lane of the wave at once as a background agent with the lane brief of template 9.7 (the lane's section of the plan, the Section 4.2 contracts, the file list, the Stage 0 tests to copy patterns from, the rules above, the worktree protocol of Section 0.1.2, and the instruction to commit on its lane branch and never push). While lanes run, do the orchestrator's own work of the wave (shared files, this file's Status line, the CHANGELOG). When a lane reports, review its diff against its brief and the contracts, rebase its branch onto dev, fast forward dev, run the whole suite with coverage, push, and delete the worktree. A lane that reports a contract problem gets the plan amended by you and the decisions log updated before anyone continues.

First, in this session: turn the instance's auto deploy switch off with a read before and after (Section 0.1.6) and record it in docs/validation/phase-2.md. Then dispatch wave A1 (lanes 1 to 4).

Do not stop for owner items: write them to docs/owner-log.md with the default you are taking and continue. Stop only at a hard stop (Section 0.1.5). Keep the Status line current in every commit that completes a task. End every session with the Section 9.3 report in chat and the Section 8.3 prompt ready for the next one.
```

### 8.3 Resume prompt for every later session

```text
Continue Device Routines in /Users/jayant/agents/deviceroutines. Read the Status line of docs/IMPLEMENTATION_PLAN.md, then the plan section the Status line names, the tail of docs/decisions-log.md and the open items of docs/owner-log.md. The rules of the kickoff prompt (plan Section 8.2) apply unchanged.

If the Status line says a restart just happened (running commit equals deployed commit, and a live validation section is open): run that section (5.3 or 6.3) from its first unrecorded step, with a read before and after every write, and record each row in the validation file it names.

If the Status line says a build is open: resume its current wave. Lanes listed as in flight have worktrees you can continue (their branch is named) or discard; lanes listed as pending are yours to dispatch. If a restart is pending and the next build is not yet open, open it; never wait for a restart.

Keep the Status line current, defer owner items to docs/owner-log.md, stop only at a hard stop (plan Section 0.1.5), and end with the Section 9.3 report.
```

### 8.4 Pause points

| Pause point | The Status line says | The owner does | The next session does |
| --- | --- | --- | --- |
| Build A exit | Build A done; `v0.3.0-beta.1` deployed, running `d00fa2f`; R1 requested; Build B wave B1 open | Owner session 1 (Section 8.1) at his convenience | Section 5.3 after the restart; Build B meanwhile in its own session |
| Build B exit | Build B done; `v1.0.0-beta.1` deployed, running `v0.3.0`; R2 requested with the staged scenario | Owner session 2 | Section 6.3 after the restart |
| Release 1.0 | live validation B recorded; O12 open | the console look; O10, O11, O13 decisions | tag `v1.0.0`; open the publication pull requests on the go ahead |
| Any owner restart | pending restart scenarios listed | announces the restart | stages Section 5.2 before, reads after |
| Context exhausted mid wave | the wave, lanes done, in flight (branch names) and pending | nothing | Section 8.3 |

## 9. Templates

### 9.1 Validation record (one per phase, in docs/validation/phase-N.md)

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| S2 window set | Live write on the sandbox device | Entity states before and after, automation entry diff | Pass |  | Jayant |

### 9.2 Stage 0 assumption record

| Field | Content |
| --- | --- |
| Assumption | A id and text |
| Item | V id |
| Status | closed, amended or deferred |
| Evidence | what was observed, where it is recorded |
| Consequence | which spec paragraph changes, if any |
| Fixtures | anonymized files produced |

### 9.3 Session report (in chat at the end of every session)

- Done: the commits and what they deliver.
- In progress: the wave, the lanes in flight with their branches, and what remains.
- Blocked, needs Jayant: the owner log ids added or changed this session, one line each; the restart request if one is pending.
- Decisions logged: the entries added to `docs/decisions-log.md`.
- Next: the next wave or section, and the prompt (Section 8.3).

### 9.4 Decision log entry

| Field | Content |
| --- | --- |
| Date |  |
| Context | the situation the PRD and spec did not cover |
| Options |  |
| Choice |  |
| Consequence |  |
| PRD register entry | yes with the D id, or no |

### 9.5 Owner log entry

| Field | Content |
| --- | --- |
| Id | O followed by a number, never reused |
| Item | what the owner does, in one sentence, with the plan or report section it comes from |
| Why the owner | a restart, a look at the UI, a device operated, a credential, an outward facing action, a decision the PRD leaves to him |
| Default meanwhile | what the work assumes or does until he answers; "none, blocking" only when nothing can proceed |
| Needed by | R1, R2, release 1.0, or none |
| Status | open, done (date), withdrawn (why) |

### 9.6 Restart bundle record (a row group in the validation file)

| Field | Content |
| --- | --- |
| Restart | R1, R2, or the owner's reason and date |
| Deployed before | the commit or tag on disk, from `device_routines_deploy_status` |
| Staged | the Section 5.2 scenarios set up, with their read before rows |
| Running after | Health `commit`, `blueprint_schema`, `owned_count`, time to `ok` |
| Read after | one row per staged scenario |

### 9.7 Lane brief (what the orchestrator hands a lane agent)

1. The goal in one sentence and the lane's section of this plan, verbatim.
2. The Section 4.2 contracts the lane consumes and produces, verbatim, with the sentence: a contract you cannot meet is a report, not a change.
3. The files the lane owns and the shared files it may add keys to; everything else is read only.
4. The spec sections and the existing tests to copy patterns from (named files).
5. The rules: no em dash; conventional commits; ruff, mypy, the whole suite and coverage before the last commit; tests in the same commit; no private data (CLAUDE.local.md and local/ are off limits, and the pre commit hooks must pass); translation keys for every string; `PARALLEL_UPDATES = 0` on platforms; behavior only in the service layer.
6. The worktree protocol of Section 0.1.2 and: commit on your lane branch, never push, never touch `dev`.
7. The report format: commits, files, the test that proves each requirement of the brief, shared file edits, anything deferred and why.
