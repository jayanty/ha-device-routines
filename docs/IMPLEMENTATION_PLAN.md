# Device Routines implementation plan

Oct 13, 2026 · @Jayant Yadav

The build order for Claude Code: Phase 0, Stage 0, then Phases 1 to 4, each with tasks, tests, validation steps and exit criteria. Behavior comes from PRD (public), design from Technical spec (public), private instance facts from Instance context (private). This tab is public and becomes `docs/IMPLEMENTATION_PLAN.md`. Section 8 is the handoff.

Status: Phase 1 done (2026-10-18): v0.1.0 released (`d00fa2f`, `main` fast forwarded, release zip built), live validation and the sentence review recorded in `docs/validation/phase-1.md`, C4 closed. Open: a restart loads `d00fa2f` on the instance, after which C1's second half (the last good commit follows Health) is checked; cleanup C2 before task 2.5, C3 in Phase 2, C5 in Phase 3, C6 optional. Live writes are pre approved with a read before and after (L26). Next: Phase 2 task 2.1.

## 0. Rules of engagement (Claude Code reads this first)

Documents in the repository: `docs/PRD.md` (behavior and the decision register), `docs/TECH_SPEC.md` (design), `docs/IMPLEMENTATION_PLAN.md` (this file: order, validation, rules), `CLAUDE.local.md` (private instance context, gitignored, never committed), `docs/stage0-report.md` (your findings), `docs/decisions-log.md` (your choices).

Operating rules:

1. Never restart Home Assistant. Never call `ha_restart` or `homeassistant.restart`, and never reload the config entry as a substitute. Say restart needed and stop. Only the opt in automation of TECH\_SPEC 10.2 may restart, and only once Jayant turns it on.
2. Read only probes and, since 2026-10-17 (decision L26), write probes and live write scenarios against the live instance are pre approved. Every write still needs a read before it and a read after it proving the state was restored or is the intended end state. Restarts (rule 1) and steps only Jayant can take (copying files into the config directory, operating devices, looking at the UI) still need him. Where a phase below says approval for a live write, read it as this rule.
3. Nothing from `CLAUDE.local.md`, `local/` or the live instance goes into a commit, fixture, test, doc, issue, pull request or commit message. The pre commit privacy check must pass; never bypass hooks.
4. Work on `dev`. Conventional commits. Push when the local gates pass. Merge `dev` into `main` only at a phase exit with green CI.
5. One phase at a time, in order; inside a phase, tasks in order unless a dependency says otherwise. Do not start the next phase before the exit criteria are met and recorded.
6. Tests ship in the same commit as the code they cover. Coverage never drops below 95 percent on `custom_components/device_routines`.
7. Decisions: proceed on the PRD defaults without asking. Record every choice the PRD and spec do not cover in `docs/decisions-log.md` (date, context, options, choice, consequence). Ask Jayant only for the Needs Jayant items of the current phase, or when a default would be unsafe.
8. Style: no em dash character anywhere; a translation key for every user facing string; `ruff` and `mypy --strict` clean before every commit.
9. Keep `CHANGELOG.md` current under Unreleased with every user visible change.
10. End every working session with the session report of Section 9.3 in chat, and update the Status line at the top of this file in the repository copy.
11. When a probe or a test contradicts the PRD or the spec: stop the task, write the finding in the Stage 0 report or the decisions log, propose the smallest design change, and continue with it unless it touches a hard constraint (PRD Section 3), in which case ask.

Definition of done for a task: code, tests, translations, docs and `CHANGELOG.md` updated; local gates green; pushed; CI green.

Definition of done for a phase: every task done; the validation steps recorded with evidence (test output, MCP read results, observations described in words); exit criteria met; `main` updated; the tag created where the phase says so.

What you have: the repository, the `gh` CLI with Jayant's authentication, the Home Assistant MCP server (reads and service calls), the local test harness. What you do not have: file access to the Home Assistant config directory. The two files that must land there (Phase 0 task 0.9) are prepared by you and installed by Jayant.

## 1. Phase 0: foundation and pipeline (no product behavior)

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

## 4. Phase 2: routines, P0 (the product)

Goal: every P0 requirement, the blueprint, the compiler, attribution, the device page controls, skip and pause, the actions, sync back, self healing and removal; release v0.2.0.

Tasks, in order:

1. **2.1 Pure core.** `domains.py` complete; `compiler.py` with `validate`, `compile` and `decompile`; `markers.py`; property tests written first.
2. **2.2 Blueprint v1** per TECH\_SPEC 5 with the V5 and V12 results applied; a test loads it through the blueprint schema and instantiates it for every domain profile and option combination.
3. **2.3 ha\_adapter write capabilities** per the V6 result: automation write and reload by id, blueprint install, helper creation, label and category creation, device attachment per the V9 result.
4. **2.4 RoutineManager:** opt in and out, update with debounce, the write path, sync back, detached and removed handling, reconcile, cleanup; Store schema v1; `migration.py` scaffold.
5. **2.5 attribution.py** with the V3 recordings as tests.
6. **2.6 Platforms:** switch (routine, catch up, respect manual, manual override), time, select (days, target), number (turn off after; turn back on after created disabled and inert until Phase 3), button (skip next, resume), datetime (paused until); the hub Clean up now button; everything through the manager.
7. **2.7 Actions** `skip_next`, `pause`, `resume`, `enable`, `disable` and `maintenance` with targets, responses, `services.yaml` and translations.
8. **2.8 Config flow** suggestions step; the options devices picker; the `on_removal` setting and `async_remove_entry`.
9. **2.9 Repairs:** `blueprint_modified`, `invalid_inputs`, `detached_routine`, `write_conflict`, `automation_load_failed` with their fix flows (`schedule_blocks_needed` arrives in Phase 3); the hub Problem sensor wired to open issues.
10. **2.10 Self healing:** every PRD 3.1 row that belongs to P0, in `reconcile` and the event handlers.
11. **2.11 Docs:** user guide sections Giving a device a routine; Skip, pause and resume; What the managed automation looks like; If you edit the automation yourself; Removing the integration.

Tests: behavior matrix B01 to B05, B08 to B13, B18 to B36 and B39 to B46 (B06, B07, B14 to B17, B37 and B38 belong to Phase 3); the integration tests of TECH\_SPEC 11.3 for everything in this phase; the round trip property; the lookalike guard; the Store migration test; the 30 day simulated run of PRD G8 (time travel through a device rename, a device removal, a restore of `automations.yaml`, a blueprint schema upgrade from a fake version 0 and a device offline for a day) asserting no unexpected Repairs issue.

Validation, live, after the deploy and restart:

- Read only: owned automations carry M1 to M8; the label, category and blueprint exist; Health is `ok`; `pytest -m live` is green.
- Write scenarios on the sandbox device named in `CLAUDE.local.md`, each with a read before and after (pre approved, rule 2). Before S2, the hand written automation driving that device is turned off. S2: set the window, timed under 60 seconds. S3: Jayant stops and starts Home Assistant across the on time. S4: manual on at noon, then a restart. S5: turn off after with a restart in the middle. S6: edit the form, then set a refused action in the form. S7: take control, plus a lookalike automation. S8: the removal flow runs in the harness only, because a single instance cannot be removed and kept live; live, only take control is exercised on the sandbox routine. S11: skip next. S12: pause for two hours by area, then a restart. S13: skip next by label with one plain device. After the phase the sandbox's hand written automation stays off while the routine drives the device; it becomes the S9 candidate in Phase 4.

Exit: tests green; every scenario recorded; `CHANGELOG.md` and `manifest.json` at 0.2.0; tag `v0.2.0`.

Needs Jayant: restarts for the deploy and for S3, S4, S5 and S12; operating Home Assistant across S3.

## 5. Phase 3: P1 features, settings, WebSocket API

Goal: FR-R2, R4, R8 and R17, the late start window, the AI summary, conflicts with Repairs, marker M9, the complete settings catalog and the WebSocket API with contract tests; release v0.3.0.

Tasks:

1. **3.1 Weekly schedule (FR-R2):** helper creation, linking, recreation and `schedule_blocks_needed`; the Days select gains Weekly schedule; the time entities become unavailable while a schedule is linked.
2. **3.2 Keep alive (FR-R4)** with D27 enforced in the compiler and at the controls; the turn back on after entity becomes active.
3. **3.3 Pulse (FR-R8)** in the blueprint form.
4. **3.4 Integration triggers and conditions (FR-R17)** per the V13 result, with `triggers.yaml`, `conditions.yaml` and translations.
5. **3.5 Late start window** input and the catch up branch for one shots.
6. **3.6 AI summary path:** options text stating exactly what is sent and where, the cache, the rate limit, the (AI) suffix, nothing during startup.
7. **3.7 Conflicts** to Repairs behind `raise_conflict_repairs`.
8. **3.8 Area assignment (M9)** behind `assign_area`.
9. **3.9 Settings** complete in options and `settings.py`, with migration of older option sets.
10. **3.10 websocket\_api.py** with every command and the subscription; `docs/api.md`.
11. **3.11 Hub Routines sensor** attributes complete: every managed routine with device, area, summary, next action, status and automation.
12. **3.12 Docs:** a user guide section per feature, and a Dashboards and scripts section showing the actions, triggers, conditions and the Routines sensor attributes with a markdown card example.

Tests: B06, B07, B14 to B17, B37 and B38; integration tests for triggers and conditions, the schedule helper lifecycle, the AI path with a fake AI Task entity (rate limit, cache, startup hold), conflicts, area assignment and settings migration; WebSocket contract tests for every command comparing payloads with the manager's results; subscription event tests.

Validation, live: the read only suite; S1 on a weekly hand written automation; the pulse and keep alive scenarios on the sandbox device; the read only WebSocket commands exercised through a one off script you provide and Jayant runs in his browser session; conversion of the two 60 minute failsafe automations stays deferred to Phase 4.

Exit: tests green; validation recorded; `CHANGELOG.md` and `manifest.json` at 0.3.0; tag `v0.3.0`.

Needs Jayant: the AI Task decision (default off, with the V4 result noted); one restart per deploy.

## 6. Phase 4: P2 features, console, publication

Goal: FR-R9, R10 and FR-M1; the console with its Routines, Today and Settings views; the brands pull request; the HACS default submission; release v1.0.0.

Tasks:

1. **4.1 Only when conditions (FR-R9)** in the form and the compiler.
2. **4.2 Sun relative times (FR-R10)** with the companion select and offset entities, advanced and disabled by default.
3. **4.3 Conversion offers (FR-M1)** behind `offer_conversions`: exact matches only, the two step Repairs flow, the `Replaced by routine` label, the original turned off and never edited further.
4. **4.4 Console:** `frontend/` with Lit and TypeScript, a Vite build, `panel_custom` registration with `require_admin`, the three views on the WebSocket API, cache busting by version, vitest tests; `release.yml` builds and ships the bundle.
5. **4.5 Brand assets** final and the `home-assistant/brands` pull request.
6. **4.6 HACS default submission** checklist: README, topics, releases, hassfest, the HACS action, brands merged.
7. **4.7 quality\_scale.yaml** final review with every rule done or exempt with a reason.
8. **4.8 Docs complete:** README with install, features, FAQ and a privacy statement; the user guide complete.

Tests: compiler and blueprint tests for FR-R9 and R10; conversion matcher tests (exact matches offered, partial matches never); console unit tests; a browser end to end test is optional and dropped if it adds flakiness.

Validation, live: S9 on the sandbox device's hand written automation; the console walked through by Jayant; the HACS install of the release on his instance when he switches channels, after which the deploy tool reports `hacs_managed`.

Exit: tests green; validation recorded; `CHANGELOG.md` and `manifest.json` at 1.0.0; tag `v1.0.0`; the brands pull request opened; the HACS default submission opened.

Needs Jayant: the console review; the channel switch decision.

## 7. Ongoing operations

- After every monthly Home Assistant release: run the CI matrix against the new core (the continue on error job becomes required once it passes), ask Jayant to update, run `pytest -m live`, and bump the minimum version within the D14 rule.
- Dependabot pull requests monthly; merge on green.
- Watch the Home Assistant release notes for native device scheduling (PRD R9).
- Issues: triage with the templates; reproduce in the harness; every fix ships with a regression test.
- Parity: a change to `tools/ha_deploy.py` lands in both repositories in the same week; the CI parity job keeps that honest.

## 8. Handoff

### 8.1 For Jayant, before the first Claude Code session

1. Export the three public tabs of this document as Markdown and keep them ready as `docs/PRD.md`, `docs/TECH_SPEC.md` and `docs/IMPLEMENTATION_PLAN.md`; Claude Code creates the repository and asks for them at task 0.8. Export the Instance context tab and hand it over as `CLAUDE.local.md`, outside the repository.
2. Confirm the GitHub user name for `<owner>` and that `gh auth status` works on the machine running Claude Code.
3. Decide the open items, or let the defaults stand: the automatic restart window (default off), AI summaries (default off), seconds for keep alive (default minutes only), the four V3 devices, and whether the instance loads `packages:`.
4. Plan to be available for: the Phase 0 bootstrap (two files, one restart), the restarts in Phase 0 and Phase 2, the Stage 0 approvals, and one sentence review in Phase 1.

### 8.2 Kickoff prompt for Claude Code

```text
You are building Device Routines, a public, HACS ready Home Assistant custom integration (domain device_routines) in the GitHub repository <owner>/ha-device-routines. I am Jayant, the owner.

Read, in this order, before writing any code: docs/PRD.md (behavior and the decision register), docs/TECH_SPEC.md (design), docs/IMPLEMENTATION_PLAN.md (order, validation and rules of engagement), then CLAUDE.local.md (private instance context; never commit, quote or copy it anywhere). If the repository does not exist yet, start with Phase 0 task 0.1; I will hand you the three docs files and CLAUDE.local.md at task 0.8.

Rules that override everything else:
1. Never restart Home Assistant and never reload the config entry as a substitute. Say restart needed and stop.
2. Read only probes and write probes against my instance are pre approved (decision L26). Every write needs a read before and a read after proving restoration or the intended end state. Restarts stay mine.
3. Nothing private (entity ids, device, area or person names, hostnames, IPs, tokens, the text of my automations) ever goes into a commit, fixture, test, doc, issue or commit message. The pre commit privacy check must pass; never bypass hooks.
4. Proceed on the PRD decision defaults without asking. Log every choice the PRD and spec do not cover in docs/decisions-log.md. Ask me only for the Needs Jayant items of the current phase, or when a default would be unsafe.
5. No em dash character anywhere. Conventional commits. ruff and mypy --strict clean. Coverage at least 95 percent.

Work the plan in order: Phase 0, Stage 0, Phase 1, 2, 3, 4. Do not start a phase until the previous one's exit criteria are recorded in the repository. Finish each task with its tests, translations, docs and CHANGELOG entry, push to dev, and confirm CI is green; CI promotes dev-stable and my instance pulls it by itself.

Start now with Phase 0. End the session with the session report from the plan (Section 9.3) and update the Status line at the top of docs/IMPLEMENTATION_PLAN.md.
```

### 8.3 Prompt for every later session

```text
Continue Device Routines. Read the Status line of docs/IMPLEMENTATION_PLAN.md and the tail of docs/decisions-log.md, then pick up the next unfinished task of the current phase. The same rules as the kickoff prompt apply.
```

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
- In progress: the task and what remains.
- Blocked, needs Jayant: the exact question or approval, one line each.
- Decisions logged: the entries added to `docs/decisions-log.md`.
- Next: the next task.

### 9.4 Decision log entry

| Field | Content |
| --- | --- |
| Date |  |
| Context | the situation the PRD and spec did not cover |
| Options |  |
| Choice |  |
| Consequence |  |
| PRD register entry | yes with the D id, or no |
