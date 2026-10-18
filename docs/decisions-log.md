# Decisions log

Every choice the PRD and the technical specification do not cover, in the order it was
made (IMPLEMENTATION_PLAN Section 0, rule 7, template 9.4). PRD decisions D1 to D34 are not
repeated here; they apply at their defaults unless an entry below says otherwise.

## 2026-10-13 L1: Python 3.14 everywhere

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 9 and 13 say Python 3.13 locally. Core 2026.10.1, the version the instance runs and Stage 0 validates, declares `requires-python >= 3.14.2`, and the matching harness release (`pytest-homeassistant-custom-component 0.13.372`) requires 3.14 as well. |
| Options | (a) Python 3.14 locally and in CI; (b) 3.13 with an older core, which is not the core the instance runs. |
| Choice | (a). `requires-python >= 3.14`, ruff `target-version py314`, mypy `python_version 3.14`, CI on 3.14. The deploy tool keeps the 3.11 compatible syntax the spec asks for. |
| Consequence | The spec's two mentions of 3.13 are superseded by this entry; nothing else changes. |
| PRD register entry | no |

## 2026-10-13 L2: privacy tooling before the integration skeleton

| Field | Content |
| --- | --- |
| Context | Phase 0 lists the integration skeleton (task 0.3) before the privacy tooling (task 0.4), yet rule 3 wants every commit to pass the privacy check, and the plan allows reordering when a dependency says otherwise. |
| Options | (a) Keep the order and accept that the first skeleton commits are unchecked; (b) build the privacy and style checks right after the tooling skeleton (0.2) and install the hooks before any integration code is committed. |
| Choice | (b). Order within Phase 0: 0.1, 0.2, 0.4, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 0.10. |
| Consequence | Every commit from the integration skeleton onward runs through the hooks. Task numbering is unchanged. |
| PRD register entry | no |

## 2026-10-13 L3: branch protection details

| Field | Content |
| --- | --- |
| Context | Task 0.1 asks for required status checks (every CI job), no force pushes, no deletions and linear history, and says nothing about administrators or about jobs that only run on `dev`. |
| Options | Enforce the rules for administrators too; require the `promote` job and the continue on error core matrix leg as checks. |
| Choice | Administrators are not bound (the owner can always recover the branch). Required checks: `lint`, `typecheck`, `test (pinned)`, `hassfest`, `hacs`, `privacy`, `style`, `deploy-tool-parity`. `promote` is not required because it runs only on pushes to `dev` and is the promotion itself; `test (latest)` is not required because the plan makes it continue on error until it passes. |
| Consequence | A phase exit is a fast forward push of a green `dev` commit to `main`, which keeps the history linear. |
| PRD register entry | no |

## 2026-10-13 L4: tooling defaults the spec leaves open

| Field | Content |
| --- | --- |
| Context | The spec names the tools but not their versions or the exact coverage scope. |
| Options | Floating tool versions; coverage on the component only. |
| Choice | ruff, mypy, hypothesis and pre-commit are pinned in `requirements_test.txt` (Dependabot bumps them monthly) so a new lint rule cannot turn CI red on its own. Coverage is measured on `custom_components/device_routines` and on `tools/` together, with the 95 percent gate on the whole, because the deploy and privacy tools are part of the safety story. The pre-commit hooks are local hooks that run the project's own virtual environment, because mypy needs the pinned core installed. |
| Consequence | `scripts/` from the sibling repository is not reproduced; the commands live in README and CLAUDE.md. |
| PRD register entry | no |

## 2026-10-13 L5: the owner's byline is allowed in the public documents

| Field | Content |
| --- | --- |
| Context | The three design documents carry the owner's name as a byline, and the instance has a person entity with the same name, so the denylist built from the registries flags the byline on every one of them. |
| Options | (a) Strip the bylines from the documents; (b) allow the byline through `tools/privacy_allowlist.txt`. |
| Choice | (b). The documents are the owner's own public work and the GitHub account already carries the name. Only the byline text is allowed; the person entity id and every other registry token stay on the denylist. |
| Consequence | `tools/privacy_allowlist.txt` lists the byline with a comment saying why. |
| PRD register entry | no |

## 2026-10-13 L6: what the denylist leaves out

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 8 lists what goes into the denylist but not what must stay out. Built literally, the list from this instance blocked the words Home Assistant, Repairs, Package, Devices, HACS, bar and main, the names of Home Assistant apps and HACS plugins, and the core's own entity ids such as `sun.sun`, so every document failed the check. |
| Options | (a) Keep the literal list and allow each false positive by hand; (b) teach the builder what identifies nothing: single generic words and stock room phrases, product and integration names of software devices (Supervisor, HACS, Spook, Backup, Sun, Met.no, the sibling integration), the core's own entity ids, and manufacturer and model strings; let a hand kept `extra` list in the capture add back anything the rules miss. |
| Choice | (b), with the word and phrase lists in `tools/make_denylist.py` and the `extra` list in the private capture. Multi word names made of generic words stay on the list unless they are stock phrases, so an area called Owl Landing is still private while Living Room is not. Device ids are always listed. |
| Consequence | 6308 tokens for this instance; the documents pass except for the byline of L5. A false positive is fixed in the builder with a test, never by editing the generated list. |
| PRD register entry | no |

## 2026-10-13 L7: a clone with private context must have a denylist

| Field | Content |
| --- | --- |
| Context | The spec says the hook checks against the local denylist where one exists and CI uses generic patterns only. A hook that silently falls back to generic patterns on the one machine that holds private context would be the failure mode that matters most. |
| Options | (a) Always fall back; (b) refuse to run when `CLAUDE.local.md` exists and `local/denylist.txt` does not. |
| Choice | (b), exit code 2 with the command to build the list. A contributor's clone has neither file and runs the generic patterns only. |
| Consequence | Rebuilding the denylist is a documented step after any registry change; `tools/privacy_check.py --staged` says so. |
| PRD register entry | no |

## 2026-10-13 L8: the anonymizer's MAC addresses live in a reserved range

| Field | Content |
| --- | --- |
| Context | Anonymized fixtures still need MAC shaped strings where the original had one, and the generic MAC pattern of the privacy check would flag them in CI. |
| Options | (a) Allow each fake address by hand; (b) replace addresses with locally administered ones under `02:00:00:00:00:` and have the check ignore that range. |
| Choice | (b). No real device carries that prefix, the check ignores exactly that prefix, and the anonymizer and the check share the constant. |
| Consequence | Registry shaped 32 character ids are already allowed inside `tests/fixtures/`; MAC addresses now follow the same idea by value rather than by location. |
| PRD register entry | no |

## 2026-10-13 L9: schemas are written with probatio

| Field | Content |
| --- | --- |
| Context | Core 2026.10 validates with the `probatio` library and only aliases `voluptuous` to it for integrations that still import the old name. Typing against the old name gives mypy the wrong types for every form and service schema. |
| Options | (a) `import voluptuous as vol` through the alias, with type stubs that no longer match; (b) `import probatio as vol`, the library the core actually ships and types. |
| Choice | (b). Probatio is a hard dependency of every core version the integration supports (2026.10 and later). The `vol` alias keeps the code readable to anyone who knows the old library. |
| Consequence | `voluptuous-stubs` left `requirements_test.txt`; the pure module import test refuses both names. |
| PRD register entry | no |

## 2026-10-13 L10: device registry lookups carry the config entry id

| Field | Content |
| --- | --- |
| Context | Core 2026.10 deprecates `async_get_device` because identifiers and connections are no longer unique across config entries; the replacement lookups take a config entry id. The PRD assumes entities from this integration attach to devices other integrations created (A10). |
| Options | Keep the deprecated call; use the new lookups. |
| Choice | The new lookups everywhere. For the hub device the entry id is the integration's own. For attaching to another integration's device (Phase 2, after Stage 0 item V9) the lookup must use that integration's entry id or `async_get_devices`, which is now the first thing V9 has to establish. |
| Consequence | V9 in the Stage 0 report records which lookup resolves another integration's device on this core. |
| PRD register entry | no |

## 2026-10-13 L11: what the deploy tool reports after a change

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 10.1 names the files that set `restart_required` (Python, the manifest, services, strings, translations), a blueprint only change as `reload_automations` and a frontend only change as `browser_reload`, but says nothing about the other files in the component (icons, the quality scale file, the blueprint directory listing) or about a change that mixes classes. |
| Options | (a) Only the named files require a restart, anything else sets no flag; (b) every file outside `blueprints/` and `frontend/` requires a restart, because Home Assistant reads all of them at startup, and the two lighter flags are set only when no restart is needed. |
| Choice | (b), implemented in `classify()` with a table test. A restart covers a reload, so a Python plus blueprint change reports `restart_required` alone. |
| Consequence | The Home Assistant package of task 0.6 can act on exactly one flag per deploy. |
| PRD register entry | no |

## 2026-10-13 L12: the deploy tool keeps v1 compatibility for the sibling

| Field | Content |
| --- | --- |
| Context | `tools/ha_deploy.py` is vendored identically in both repositories (PRD D15). The sibling's instance already runs v1 with `--branch dev`, `--config-dir`, backups under `<config>/<domain>/backups`, a token file under `<config>/<domain>/` and a `DEVICE_LINKS_DEPLOY_TOKEN` variable. |
| Options | (a) Break those callers and update the sibling's configuration in the same pull request; (b) keep every v1 spelling working: `--branch` and `--config-dir` as aliases, legacy backups still listed and restorable, the legacy token file still read, and `<DOMAIN>_DEPLOY_TOKEN` honoured next to the generic `HA_DEPLOY_TOKEN`. |
| Choice | (b). New backups go to `<config>/.ha_deploy/<domain>/backups`; a rollback consumes the newest backup wherever it lives. |
| Consequence | The backport pull request to the sibling changes no configuration there. The CI parity job compares the file with the sibling's `main` only when that repository is readable; while it is private the job records a skip, not a pass. |
| PRD register entry | no |

## 2026-10-13 L13: the package helpers restore their values, and the post restart check remembers the last good commit

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 10.2 gives the package helpers initial values (auto deploy on, auto restart off, the window 03:00 to 04:00) and says the post restart check compares "a deploy newer than the last successful load". Home Assistant's `initial:` key forces a helper back to that value on every restart, which would undo the owner's choice, and nothing in the instance records when the integration last loaded. |
| Options | (a) `initial:` on every helper and a guess at the last load; (b) no `initial:` (the helpers restore their values, the Home Assistant best practice), one extra `input_text` that the post restart check writes with the commit of every successful load, and a rollback only when the deployed commit differs from that value. |
| Choice | (b). The bootstrap gains one manual minute: turn auto deploy on and set the window once. The extra helper also keeps the check from rolling back an install that has never worked, which is what an unconfigured integration looks like. |
| Consequence | Task 0.9's check lists the helper with the others; the three automations of the spec stay three, the recording branch lives in the post restart check. |
| PRD register entry | no |

## 2026-10-13 L14: the HACS validation ignores the brands check until Phase 4

| Field | Content |
| --- | --- |
| Context | The HACS action verifies that the domain exists in `home-assistant/brands`. That pull request is Phase 4 task 4.5, and the check cannot pass before it is merged for a reason unrelated to this repository. |
| Options | (a) Let the job fail until Phase 4; (b) pass `ignore: brands` to the action now and remove it when the brands pull request merges. |
| Choice | (b), with the reason in the workflow. Every other HACS check runs. |
| Consequence | Task 4.6 removes the ignore. |
| PRD register entry | no |

## 2026-10-13 L15: main was moved early to the commit that holds the license

| Field | Content |
| --- | --- |
| Context | The HACS validation reads the repository's license from the GitHub API, which detects it on the default branch. The plan's first commit on `main` holds only `.gitignore`, so every CI run on `dev` failed the HACS job on "no license" and the promotion of `dev-stable` could never run, while the plan merges `dev` into `main` only at a phase exit with green CI. |
| Options | (a) Ignore the license check in the HACS job until the phase exit; (b) fast forward `main` to the skeleton commit that added the LICENSE, an ancestor of `dev` with no product code, so the detection works and the phase exit stays a fast forward. |
| Choice | (b), pushed as the owner with the protection's administrator bypass, since no CI had run on that commit. Every later move of `main` happens at a phase exit with green CI as the plan says. |
| Consequence | `main` is at the skeleton commit until the Phase 0 exit; the HACS job validates the real license. |
| PRD register entry | no |

## 2026-10-14 L16: the post restart check records a load that happens during startup

| Field | Content |
| --- | --- |
| Context | Stage 0 item V11 showed that after a restart the Health sensor turned `ok` about ten seconds before Home Assistant fired its start event. Automations arm their triggers only once Home Assistant has started, so the `to: ok` trigger of the post restart check (L13) never fired and `input_text.device_routines_last_good_commit` kept the commit of the load before. The run that did fire, the start branch, was queued, so a healthy load after startup also waited three minutes behind its delay. |
| Options | (a) Keep the state trigger only and accept a stale last good commit, which weakens the rollback guard over time; (b) also record the commit in the start branch when Health is `ok` after the three minute wait, and run the automation in `parallel` mode so the state trigger records at once. |
| Choice | (b). The state trigger stays for a load after startup; the start branch covers a load during startup and then stops before the rollback logic. |
| Consequence | The installed package must be replaced with the new file once (owner's step, no restart: an automation reload is enough). A test in `tests/tools/test_ha_package.py` holds the behavior. |
| PRD register entry | no |

## 2026-10-14 L17: the deploy automation ignores the first tag reading after a start

| Field | Content |
| --- | --- |
| Context | Stage 0 item V11: after the rollback and restart 2, `sensor.device_routines_dev_stable` changed from `unavailable` to the tag it already pointed at. The deploy trigger only allowed `not_to: [unknown, unavailable]`, so that change would have redeployed the commit that had just been rolled back. It was skipped only because the sensor's first poll came before the triggers were armed. After an automatic rollback of a broken build, the next restart could put the broken build back. |
| Options | (a) Keep the trigger and rely on the timing; (b) add `not_from: [unknown, unavailable]`, so only a real move of the tag between two readings deploys; (c) compare the tag with the deployed commit in a condition, which needs a status call on every start. |
| Choice | (b). A tag that moved while Home Assistant was down is picked up by the next move of the tag or by `shell_command.deploy_device_routines` by hand; the tool is idempotent either way. |
| Consequence | Replacing the installed package (L16) brings this change too. A test in `tests/tools/test_ha_package.py` holds it, and the package README says so. |
| PRD register entry | no |

## 2026-10-14 L18: sha prefixes are sliced inside the message templates

| Field | Content |
| --- | --- |
| Context | Stage 0 item V11: the deploy automation's `short_sha` variable rendered as the integer 842088276435, because Home Assistant gives rendered templates native types and that commit's first twelve characters are all digits. A prefix such as `1234e567...` would even become a float. |
| Options | (a) Keep the variable and accept odd values in rare cases; (b) slice the commit inside each notification message, where the result is always text. |
| Choice | (b). Variables keep whole JSON objects only. |
| Consequence | A test refuses a sha slice inside `variables:`. Comes with the package replacement of L16. |
| PRD register entry | no |

## 2026-10-14 L19: automation captures are scrubbed before they are anonymized

| Field | Content |
| --- | --- |
| Context | Stage 0 item V2 captured 39 automation configs. The anonymizer replaces denylisted tokens only, and the trial run left a remote access URL, a webhook id, phone notify services, the owner's initials and registry ids of entities in the output, besides every alias, description and note, which are automation text the privacy rule forbids. The denylist builder also dropped the two letter initials added by hand, against its own comment that extras are never filtered. |
| Options | (a) Hand edit the fixtures; (b) a scrub step before the anonymizer that keeps every structural key and replaces free text and opaque values with generic stand ins, plus a fix so hand kept extras bypass the length and generic word filters. |
| Choice | (b): `tools/scrub_automations.py` (aliases, descriptions, notes, stop texts, titles, messages and names become generic; URLs, webhook ids, notify services and registry entity ids map to stand ins consistently across files; files become `automation_NN.json`), and `build_denylist` keeps every extra as given. Each with tests. |
| Consequence | The fixture pipeline is capture, scrub, anonymize, privacy check, read every remaining string by hand. Trigger ids and data values the owner chose are kept, because templates and trigger conditions refer to them; the denylist covers names inside them. |
| PRD register entry | no |

## 2026-10-17 L20: a timer that expired while Home Assistant was down is caught up by the integration

| Field | Content |
| --- | --- |
| Context | Stage 0 V10 (A5b): the timer component finishes a restored timer whose end has passed while the entity is added during startup, and automations arm their triggers only in a startup job after that. Neither the `timer.finished` event trigger nor the purpose specific `timer.finished` trigger sees that finish; only a start trigger runs, and by then the timer reads `idle` with `last_transition: finished`, which a timer that finished normally an hour earlier also reads. A5b as written fails for a routine. |
| Options | (a) Accept the miss, so a Turn off after that ran out during a restart never turns the device off; (b) a blueprint start branch that acts on `idle` plus `last_transition: finished`, which also fires after a normal finish followed by a manual change during the downtime; (c) the integration reads the timer's pre shutdown state from the restore state helper at setup (`active` with a `finishes_at` in the past means the finish was missed) and, once Home Assistant has started, fires `device_routines_timer_caught_up` with the device id; the blueprint gets a second `timer_done` trigger on that event, so the normal branch runs. |
| Choice | (c). It is exact and keeps the action in the automation. The read goes through `ha_adapter` (`restore_state.async_get(hass).last_states`). |
| Consequence | TECH_SPEC 4.2 gains the capability row, 5.3 the event trigger, 7 the startup step. Behavior without the integration (PRD 3.1 and 9.2): a timer that runs out during a restart is not caught up until the integration is back, which the user guide states. A harness test (`tests/stage0/test_v10_timer_restore.py`) holds the core behavior so a core change is noticed. |
| PRD register entry | no (A5b amended in the Stage 0 report) |

## 2026-10-17 L21: daylight saving rules follow what the core time trigger really does

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 3.6 said a skipped wall clock time runs at the first valid instant after it and a repeated one runs once. Stage 0 V10 (A7) on cores 2026.10.1 and 2026.10.2, the 2026 United States and European dates: a skipped time does not run that night at all, and a repeated time runs twice, once per offset, an hour apart. PRD 5.2 asks that the behavior follow the core time trigger and be documented. |
| Options | (a) Make routines differ from the core with an extra trigger or an integration side catch up; (b) mirror the core in `nextrun` and the sentences, and document it. |
| Choice | (b). Every on and off action is guarded by the device state, so the second run at a repeated time changes nothing; a pulse at a repeated time pulses twice, which the guide states, and a routine whose start time falls in the skipped hour does not start that day. |
| Consequence | TECH_SPEC 3.6 DST paragraph rewritten; the user guide documents both nights; `nextrun` tests use the 2026 dates and match `tests/stage0/test_v10_schedule_dst.py`. |
| PRD register entry | no |

## 2026-10-17 L22: Paused until stays a datetime entity, read through one template condition

| Field | Content |
| --- | --- |
| Context | Stage 0 V12 (A13): the time trigger accepts `input_datetime` and `sensor` entities only and the time condition `input_datetime`, `time` and `sensor` only, so a `datetime` entity fails both, as PRD 9.5 expected. The PRD 9.5 alternative, a timestamp sensor, works for the trigger but not for the condition: the time condition takes only the local time of day of a timestamp sensor, so a pause until tomorrow 07:30 reads as over at 08:00 today. |
| Options | (a) Timestamp sensor for both, which breaks every pause longer than a day; (b) timestamp sensor for the trigger and the template for the condition, which adds an entity per routine; (c) keep the `datetime` entity, use the one template condition of TECH_SPEC 5.4 for `not_paused`, omit `pause_ended`, and let the integration call resume at the stored time (PRD 9.5). |
| Choice | (c). The template is `{% set s = states(entity) %}{{ s in ('unknown', 'unavailable', '') or as_datetime(s) <= now() }}`, proven in the harness for unknown, unavailable, past and future values. A `datetime` entity that implements RestoreEntity gets its value back after a restart (harness). |
| Consequence | TECH_SPEC 5.3 drops `pause_ended` and 5.4 makes the template the only path; the blueprint's `homeassistant.min_version` is 2026.10.2. Without the integration a pause still ends, at the next scheduled trigger, as PRD 9.5 says. |
| PRD register entry | no (A13 closed with the designed fallback) |

## 2026-10-17 L23: helpers are created through their WebSocket commands, dispatched in process

| Field | Content |
| --- | --- |
| Context | Stage 0 V7 (A5): the timer and schedule storage collections that TECH_SPEC 4.2 names are local variables of each component's setup, so integration code cannot call `async_create_item`. The registered WebSocket commands (`timer/create` and so on) reach the same collection with the same schema, and they require an administrator. |
| Options | (a) Find the collection by introspecting listeners, fragile across releases; (b) D2(b), the WebSocket API over loopback with a token the user creates, which breaks the zero field config flow (D33); (c) dispatch the registered commands in process through an `ActiveConnection` whose user is a system user in the administrators group that the integration creates once; (d) own timer entities, which would stop routines working without the integration. |
| Choice | (c). It uses only the documented command contract, needs no secret and no network, and the harness and the live probe exercised the identical handlers. The system user is created at first setup, its id kept in the config entry data, and removed when the entry is removed. |
| Consequence | TECH_SPEC 4.2 helper row rewritten; `ha_adapter.check` verifies that the four commands are registered and disables editing with `adapter_incompatible` otherwise. Diagnostics list the system user's id, never a token (none exists). The D2(b) fallback is no longer needed for helpers. |
| PRD register entry | no |

## 2026-10-17 L24: the shipped blueprint carries no source_url

| Field | Content |
| --- | --- |
| Context | Stage 0 V5 and V8: a blueprint saved with a `source_url` gets the core's re-import action, and on instances with Spook an update entity that offers to replace the file from that URL. The Device Routines blueprint is managed by the integration (TECH_SPEC 5.1 and 5.6); a replacement from GitHub would put a different version under the routines and raise `blueprint_modified`. The Home Assistant best practice asks for a `source_url` on shared blueprints. |
| Options | (a) Keep a `source_url` and handle the replacement as a modification; (b) ship the file without `source_url`, since it is installed and upgraded by the integration, never imported by hand. |
| Choice | (b). The description says the file is managed by Device Routines. |
| Consequence | TECH_SPEC 5.1 says so; a test in Phase 2 refuses a `source_url` in the shipped blueprint. |
| PRD register entry | no |

## 2026-10-17 L25: entities reach a device page as a linked record

| Field | Content |
| --- | --- |
| Context | Stage 0 V9 (A10): core 2026.10 gives every device record a single config entry and makes identifiers unique per entry. An entity whose `DeviceInfo` copies the user's device identifiers now lands on a new record of this integration carrying those identifiers, which the core lists as a linked device of the user's device; setting the entity's `device_id` to the user's device directly is undone whenever the platform adds the entity. |
| Options | (a) The registry `device_id` path, which does not survive a load; (b) `DeviceInfo` with the identifiers and name copied verbatim from the registry entry (the ha-device-links approach), accepting the linked record; (c) a child device under the user's device (`async_get_or_create_child`), which shows as a separate sub device. |
| Choice | (b), pending the live look C4 at how the device page presents a linked record. The name is copied too, or the record and entity ids are named after the config entry. |
| Consequence | TECH_SPEC 4.2 attach row rewritten; the manager removes this integration's linked record when the user's device goes (the registry keeps it otherwise), as part of the PRD 3.1 device removal row. If C4 shows the entities off the user's page, the owner decides between (c) and a dedicated design. |
| PRD register entry | no |

## 2026-10-17 L26: live writes no longer need a per item approval

| Field | Content |
| --- | --- |
| Context | Plan rule 2 and CLAUDE.md rule 2 asked for the owner's explicit approval of every write probe and live write scenario. The owner changed the rule on 2026-10-17 for everything going forward. |
| Options | (a) Keep per item approvals; (b) pre approve writes and keep the read before and the read after. |
| Choice | (b), the owner's instruction. Restarts (rule 1) stay forbidden, and steps only the owner can take (copying files into the config directory, operating devices, looking at the UI) still need him. |
| Consequence | Plan Section 0 rule 2, the Phase 2 to 4 validation lines, the kickoff prompt, TECH_SPEC 11.7 and CLAUDE.md rule 2 now say so. Every live write is still recorded with its read before and after in the phase's validation record. |
| PRD register entry | no |

## 2026-10-17 L27: the sentence phrase table lives in sentences/<lang>.json

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 3.8 puts the sentence tables in a `sentence` section of `translations/<lang>.json`. hassfest validates `strings.json` against a fixed schema of sections (config, options, entity, exceptions, issues, services and the like) and rejects others, and the translations must equal `strings.json` (a repository test). |
| Options | (a) Abuse an allowed section, such as `exceptions`, for sentence fragments; (b) a flat phrase table per language in `custom_components/device_routines/sentences/<lang>.json`, loaded once by the summary and handed to the pure `sentence.Writer`. |
| Choice | (b). Every phrase is still a key in a per language file, so a language is added without code; a test fails when a phrase is missing or unused. |
| Consequence | TECH_SPEC 3.8 reads the table from `sentences/` instead; the hub and entity names stay in `strings.json` as before. A missing language falls back to English. |
| PRD register entry | no |

## 2026-10-17 L28: the parser returns structure; the writer and the summary build the item

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 3.5 gives `summarize(config, device, lang) -> list[SummaryItem]`, which would make the parser format times and know languages and time formats, and 3.6 lists `skip_target`, which needs the Paused until semantics of Phase 2. |
| Options | (a) As written; (b) `parser.summarize(config, device) -> list[ParsedLine]` (structure only), `sentence.Writer` turns a line into text and a next run into the state, and `summary.py` assembles `SummaryItem`; `skip_target` arrives with the compiler in task 2.1. |
| Choice | (b). Each module has one job and the parser's tests do not depend on wording. `DeviceContext` carries the device's entities with their effective area, floor and labels and the registry id map, so registry id references resolve in the parser without Home Assistant. |
| Consequence | TECH_SPEC 3.5 and 3.6 signatures read as above. `nextrun.earliest` picks the state's action; two lines with opposite actions at the same instant show "Next: <time>", because their conditions decide. |
| PRD register entry | no |

## 2026-10-17 L29: grammar edges the PRD leaves open

| Field | Content |
| --- | --- |
| Context | FR-S2 lists what the parser understands but not how it treats keys it does not know, delays before the first action, else and default branches, or how durations read. G5 asks for zero wrong lines. |
| Options | (a) Read what looks familiar and ignore the rest; (b) refuse anything not listed. |
| Choice | (b), with these rules: a trigger or condition with an option the grammar does not list is outside the grammar; a delay before the first action on the device, any repeat, wait, variables or event step, and a default branch after non trigger conditions make "plus custom logic"; an else branch after understood conditions counts one more condition; a trigger condition inside and, or or not is custom logic; time patterns with seconds other than a fixed second are not read (minute precision); durations under two hours read in minutes ("60 min"), longer ones in hours. |
| Consequence | Every rule has a unit test in `tests/unit/test_parser.py` or `test_sentence.py`; the golden corpus review of task 1.6 may refine wording, never by special case. |
| PRD register entry | no |

