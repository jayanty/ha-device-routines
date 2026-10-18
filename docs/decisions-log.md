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
| Choice | (b), confirmed by the live look C4 on 2026-10-17: the device page shows the linked record's sensor in the user's device Sensors card. The name is copied too, or the record and entity ids are named after the config entry. |
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

## 2026-10-17 L30: discovery walks the automations; one index, one timer

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 4.2 and 4.4 describe discovery per device (ask `automations_with_area`, `_floor` and `_label` with the ids the device resolves to), a per device coalescing queue and one point in time listener per device. |
| Options | (a) As written: for every device, call each helper, each of which loops over every automation; (b) walk each loaded automation once, ask the reverse helpers (`entities_in_automation`, `devices_in_automation`, `areas_in_automation`, `floors_in_automation`, `labels_in_automation`) which ids it names, resolve each to the devices it reaches, and let the parser keep only actions on each device. |
| Choice | (b). It reads the same helper data (the A3 probe proves the reverse helpers name ids as written), costs one pass instead of devices times automations, and finds the same pairs. The parsed index is rebuilt as a whole, debounced two seconds; the views (next runs, sentences, conflicts) are recomputed from it without parsing, and one point in time listener at the earliest next run of any device replaces the per device ones, since a view recompute is cheap. Registry events caused by this integration's own entities and linked records are filtered out, so adding a Schedule sensor does not rebuild the index. |
| Consequence | TECH_SPEC 4.4 reads as above. `DeviceEntry.config_entries` is deprecated in core 2026.10; the code uses `config_entry_id`. |
| PRD register entry | no |

## 2026-10-18 L31: state triggers waiting for the same change share one clause

| Field | Content |
| --- | --- |
| Context | Phase 1 sentence review (task 1.6): the owner confirmed nine of ten live lines and called the tenth confusing: an automation with five state triggers that each wait for any change read "when A changes or when B changes or ..." five times. |
| Options | (a) Leave it; (b) a special case for that automation, which the plan forbids; (c) a general rule: state triggers with the same to, from and duration merge into one clause listing their subjects. |
| Choice | (c). "When A, B or C changes or when Home Assistant starts: on". The order of first appearance is kept; other trigger kinds keep their own clauses. |
| Consequence | A unit test in `tests/unit/test_sentence.py`; the golden corpus changed in exactly the two lines of that shape, reviewed in the diff. |
| PRD register entry | no |


## 2026-10-18 L32: two restarts for everything that is left: builds, lanes, restart bundles, the owner log

| Field | Content |
| --- | --- |
| Context | The plan asked for one phase at a time with live validation and a restart per phase, plus a restart each for S3, S4, S5 and S12: at least seven more owner restarts after the five of the first five days, on a production instance, with sessions stopping at every one and at every owner question. Every live capability the routines need was already probed on the instance in Stage 0 (V3, V5 to V9, V13), and the harness runs the same core with cold starts over restore state. |
| Options | (a) Keep the phase by phase loop; (b) build Phases 2 and 3 together in the harness as one build with parallel lanes, then one restart; Phase 4 as a second build with a second restart; stage every restart dependent scenario before a restart that happens anyway; defer every owner item to a log with a default; keep the instance's auto deploy switch off while a build is open so an incidental restart loads nothing unvalidated. |
| Choice | (b). IMPLEMENTATION_PLAN Section 0.1 is the operating model; Sections 4 to 6 are the builds; `docs/owner-log.md` is the register; rules 12 to 15 were added and rules 4, 5, 7 and 10 amended. Live validation confirms what the harness proved and never discovers; a live finding becomes a harness test first. The restart halves of S3, S4, S5 and S12 are staged by the clock on whichever restart comes (R1, R2 or an owner's own), and stand on their harness rows otherwise. |
| Consequence | Phase 2 and Phase 3 exits are harness exits recorded in `docs/validation/phase-2.md` and `phase-3.md`; their live rows are filled after R1. Owner time is batched into two sessions (plan 8.1). CLAUDE.md rules 4, 5 and 8 point at the model. Auto deploy is toggled by the session with a read before and after under L26. |
| PRD register entry | no (process; PRD 13.3's phase scope is unchanged, only the restart cadence) |

## 2026-10-18 L33: v0.2.0 is skipped; beta tags at harness exits, full tags after live validation

| Field | Content |
| --- | --- |
| Context | PRD 13.3 names v0.2.0 for Phase 2 and v0.3.0 for Phase 3. With L32 both ship in one build, and the release workflow already treats `-beta.N` tags as pre releases. |
| Options | (a) Tag v0.2.0 and v0.3.0 on the same commit; (b) skip v0.2.0, tag `v0.3.0-beta.1` at the harness exit so the deploy tool has a named ref and HACS users opting into pre releases can test, and tag `v0.3.0` after live validation A; the same for `v1.0.0-beta.1` and `v1.0.0`. |
| Choice | (b). A full tag always follows a live validation record; a beta tag follows a harness record. |
| Consequence | `CHANGELOG.md` goes from 0.1.0 to 0.3.0; `manifest.json` carries 0.3.0 at the Build A exit (the release workflow checks the tag's version against it, and `0.3.0-beta.1` is compared as `0.3.0`, which the workflow must strip; task A4.5 adjusts `release.yml` so a `-beta.N` suffix is ignored in that comparison). The sandbox instance runs the beta between the two tags. |
| PRD register entry | no |

## 2026-10-18 L34: markers.py is seeded before wave A1 so the adapter guard uses the real predicate

| Field | Content |
| --- | --- |
| Context | Plan Section 4.3 has lane 1 create `markers.py` while lane 3, in parallel, writes the adapter whose write guard must refuse anything `markers.is_owned` rejects. A local stub in lane 3 would duplicate a security invariant (CLAUDE.md Section 3: the adapter refuses unowned configs whatever the caller) and make the rebase order of the two lanes matter. |
| Options | (a) The stub of the plan; (b) the orchestrator lands the M1 and M2 functions on `dev` before dispatching the wave, and lane 1 extends the module. |
| Choice | (b). `markers.py` on `dev` holds `AUTOMATION_ID_PREFIX`, `BLUEPRINT_PATH`, `automation_id`, `has_routine_id` (M1 alone, which `is_detached` needs) and `is_owned`, each tested at 100 percent. `BLUEPRINT_PATH` is defined in `markers` and re exported by `compiler`, so the contract name `compiler.BLUEPRINT_PATH` holds and `markers` stays free of a compiler import. |
| Consequence | Plan Section 4.2 (`markers.py` row) and the lane 1 and lane 3 file lists amended. TECH_SPEC 3.4 is unchanged; `has_routine_id` is the M1 half of `is_owned` that TECH_SPEC 4.2's take control detection already describes. |
| PRD register entry | no |

## 2026-10-18 L35: attribution edges TECH_SPEC 4.3 leaves open

| Field | Content |
| --- | --- |
| Context | Lane 4 implemented the attributor. TECH_SPEC 4.3 does not say what counts as a change, when the 30 second grace starts if the integration is set up in a running instance, which source wins when a run context also carries a user id, or how the sink calls are ordered. |
| Options | For each: read every state event, or only value changes between available states; a grace from setup, or from the started event only; user id first, or the run map first; awaited sink calls, or tasks. |
| Choice | A change is a new state value between two available states: attribute updates, an entity appearing or going away and every transition to or from `unknown` or `unavailable` are ignored (a device coming back is catch up's job, PRD FR-R5, and an override set by its return would suppress that catch up). The grace runs while Home Assistant boots and until 30 seconds after the started event; set up in a running instance (install, reload) there is none. The run map wins over a user id (a script a person starts from a dashboard is an automation change), per the order of TECH_SPEC 4.3. Every value change of a watched entity reaches the sink, even when the on and off reading does not move, so `last_change_source` stays current; sink calls run as eagerly started tasks in event order. The run event names are local constants pinned to the core's by a test, because only the adapter may import the automation and script components. |
| Consequence | Lane 5 implements `OverrideSink` idempotently and applies its state before its first await; `await attributor.async_start()`, `attributor.async_stop()` without await. Plan Section 4.2 attribution row annotated. |
| PRD register entry | no |

## 2026-10-18 L36: timer and schedule helpers carry no device

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 4.2 and L23 attach each routine helper to its device through the entity registry. Lane 3 found that on core 2026.10 the registry accepts a `device_id` for an entity without a config entry but drops it the next time the entity is added (an entity id change or a restart), logging that attaching a device to such an entity is deprecated and breaks in 2027.8. A canary test, `test_a_helper_does_not_keep_a_device_on_this_core`, holds the behavior. |
| Options | (a) Keep setting the device and accept that it vanishes; (b) give helpers the entity id and the label only; (c) own the helpers through a config entry of this integration, which the core's helper collections do not offer. |
| Choice | (b). The label, the entity id slug (`timer.routine_<slug>`, `schedule.routine_<slug>`) and the Store tie a helper to its routine; `async_create_helper` takes no device. |
| Consequence | TECH_SPEC 4.2 helper row amended. The device page never showed helpers (they are inputs of the routine, not device controls), so nothing user visible changes. If the canary starts failing on a later core, the device link can return. |
| PRD register entry | no |

## 2026-10-18 L37: adapter semantics the manager relies on, and the two removal capabilities

| Field | Content |
| --- | --- |
| Context | The Section 4.2 contract named the adapter's functions but not the write guard's exact meaning, and it had no path for the two writes the removal flow needs: take control of an owned automation (a config without M2, which the write guard refuses by design) and removing the system user (L23). |
| Options | For the guard: a file hash or an entry hash. For removal: relax the write guard, or add one narrow capability per need. |
| Choice | The guard is the file hash the adapter itself handed out at the caller's read (`file_hash` right after `async_read_automation`); a move of the file is retried once against a fresh read provided the target entry is unchanged since the guarded read, a second move or a changed target raises `WriteConflictError`; other entries' concurrent changes are never lost; comments are dropped as the core editor drops them. `async_install_blueprint` writes the exact shipped text after `async_add_blueprint`, because the core re dumps YAML and the shipped hash compare of TECH_SPEC 7 needs the bytes. `is_detached` is M1 without ownership, which also covers a `use_blueprint` pointed elsewhere. Removal gets two narrow capabilities, added by lane 10: `async_release_automation` writes an entry without M2 only over an entry owned at that moment, and `async_remove_system_user`. The write guard stays as it is. |
| Consequence | Plan Section 4.2 adapter row and lane 10's file list amended. The invariant of CLAUDE.md Section 3 holds: every write targets an owned entry. |
| PRD register entry | no |

## 2026-10-18 L38: compiler and skip target edges

| Field | Content |
| --- | --- |
| Context | Lane 1 built the compiler and `skip_target`. The blueprint inputs carry no `days` value, only day sets, so a round trip needs a canonical form; a profile without an on action still needs a valid `on_action` input; TECH_SPEC 3.3 lists fewer rejections than the inputs need; the contract's `skip_target` has no way to see a running countdown; and a weekly schedule's block end is not in the schedule entity's state. |
| Options | Canonical form or a `days` input (a blueprint change); an empty or a safe `on_action`; ranges in `validate` or in the entities only; a new argument or a lookup for the countdown; block data from the helper, or Skip next unavailable outside a block. |
| Choice | `compiler.canonical` maps Some days with a named set to that name, keeps `day_set` only for Some days and `schedule_entity` only for a weekly schedule, and drops microseconds; `decompile(compile(s)) == canonical(s)`, and `decompile` reads the primary inputs only, so the next write repairs derived inputs a form edit left stale. A profile without an on action carries its off action in `on_action` (a valid service that can only make the device safer), with every on feature disabled. `validate` also rejects times with Weekly schedule and minutes out of range (durations 0 to 1440, late window 0 to 180, pulse 1 to 1440, steadiness 0 to 1440). `skip_target` takes a keyword `countdown_ends` for an active timer. Skip next outside a weekly schedule block returns None in lane 1; lane 14 closes the gap by reading the helper's blocks through the adapter and skipping the next block start with its end, as D18 does for a window. With `late_start_window_min` 0 the compiler emits `late_window_end` equal to `on_time`; the blueprint guards that case so 0 means no late start (lane 2 told). |
| Consequence | Plan Section 4.2 compiler, nextrun, sentence and markers rows annotated with the landed names; lane 14's file list gains `nextrun.py`. The Writer's new state methods are pinned for lane 7. |
| PRD register entry | no |

## 2026-10-18 L39: wave A2 starts with lanes 6 and 7; maintenance takes its target

| Field | Content |
| --- | --- |
| Context | Plan Section 4.4 dispatches lanes 5, 6 and 7 together, but lane 5 (the manager) consumes lanes 6 and 7 and lane 2's blueprint fixtures, while lanes 6 and 7 need neither lane 2 nor lane 5. The contract `maintenance.async_run(hass, entry, action, dry_run)` would make lane 6 read a manager from the entry's runtime data, a field lane 5 adds. |
| Options | (a) Dispatch the three together and let lane 5 rebase onto lanes 6 and 7 when they land; (b) dispatch lanes 6 and 7 as soon as lane 1, 3 and 4 have landed, and lane 5 when lane 2 lands, by when lanes 6 and 7 are likely on `dev`. For maintenance: (a) keep the entry parameter; (b) pass the target. |
| Choice | (b) and (b). `async_run(hass, target, action, dry_run)` with a `MaintenanceTarget` protocol in `maintenance.py`; services, the hub button and the WebSocket command pass `entry.runtime_data.manager`. Lane 6 may also export `async_migrate_entry` from `__init__.py` and bump the entry's `MINOR_VERSION` in `config_flow.py`, one line each. |
| Consequence | Plan Section 4.2 maintenance row and lane 6's file list amended; the Status line names the lanes in flight. |
| PRD register entry | no |

## 2026-10-18 L40: blueprint edges, and what they ask of the manager

| Field | Content |
| --- | --- |
| Context | Lane 2 wrote the blueprint and proved B01 to B43. Three behaviors of the core and of D19 and D20 together were not visible in the spec: setting a datetime entity to the instant it already holds is not a state change; D20's catch up at a pause end would apply a skipped window end one minute late, against D19's "device stays as is until the following action"; and the pause branch pauses a running timer, so a skipped countdown would resume later. TECH_SPEC 5.4 and 5.5 also leave the shape of input switched rules and of the refusal guard open. |
| Options | For D19: (a) pause until the following action, which still ends in a catch up that can contradict D19 when that action is a pulse; (b) Skip next on a window end also turns the Manual override on, so the pause end's catch up waits and the next scheduled time clears the override (FR-R6). For the pause end: set Paused until to now, or clear it. |
| Choice | (b), and the manager clears Paused until at the stored end (an early Resume may set it to now or clear it); Resume also clears an override the skip set, so undoing a skip catches up; Skip next on a running countdown cancels the timer before it writes Paused until. Blueprint shapes: no template beyond `not_paused`; input switched rules use `enabled:` on triggers, conditions and actions; checks on helper entities use the purpose specific conditions (`switch.is_on`, `timer.is_active`, `timer.is_paused`, `schedule.is_on`), which are false for a sentinel without an error; the refusal guard (the third line after the compiler and sync back) keys on the target and refuses every on action when the target reads a lock or alarm state, unknown or unavailable, or has the garage, gate, door or gas device class; the blueprint honors the override whatever `respect_manual` says, because only the integration sets it; the pause end runs the window catch up only, never the one shot late start; a late start window of 0 means no late start. |
| Consequence | Plan Section 4.2 manager row lists the three manager duties; lane 5's brief carries them. B32 proves both outcomes of a window end skip, B33 the countdown skip, and `test_setting_paused_until_to_its_own_stored_instant_is_not_heard` pins the core behavior. |
| PRD register entry | no (D19 and D20 stand; this is how they combine) |

## 2026-10-18 L41: the Repairs raise and clear helper is seeded before the manager

| Field | Content |
| --- | --- |
| Context | Lane 5 (wave A2) raises most catalog issues (`invalid_inputs`, `detached_routine`, `blueprint_modified`, `schedule_blocks_needed`, `write_conflict`, `automation_load_failed`), while `repairs.py` with its fix flows is lane 11's in wave A3. Several routines can each have the same issue open, and the core keys issues by one id. |
| Options | (a) Lane 5 adds its own raise calls and lane 11 reworks them; (b) the orchestrator lands the contract's `async_sync_issue` with the catalog first. |
| Choice | (b): `async_sync_issue(hass, issue_id, present, placeholders=None, *, subject=None)` raises or clears a catalog issue idempotently; per routine issues carry the automation id as `subject`, so the registry id is `<issue>_<subject>` and the translation key stays the catalog id; fixable per `FIXABLE`; `adapter_incompatible` and `automation_load_failed` are errors, the rest warnings. A title and description per catalog issue are in `strings.json`. |
| Consequence | Plan Section 4.2 repairs row amended. Lane 11 adds `async_create_fix_flow` and the fix flow strings (hassfest takes either a description or a fix flow per issue). The hub Problem sensor lists registry ids, so it shows one entry per affected routine. |
| PRD register entry | no |

## 2026-10-18 L42: Store, settings and maintenance edges

| Field | Content |
| --- | --- |
| Context | Lane 6 built the Store, the migrations and the maintenance actions. Open points: what Store version 0 is; whether a newer stored minor version loads (the core convention) or is refused; how the entry's minor version relates to the options version; when the blueprint schema migration runs; and how cleanup splits between maintenance and the manager. |
| Options | For a newer minor version: load it as the core does (and drop keys this code does not know at the next save), or refuse it and keep the file. The others: as chosen below or the obvious alternatives. |
| Choice | Store version 0 is the PRD 10.2 layout; migrating it adds the TECH_SPEC 6 fields at their first values. A newer stored version, minor included, is refused with a translated `StoreVersionError` and the file is left on disk: after a downgrade the integration does not set up (routines keep running in Home Assistant) instead of silently losing what the newer version stored; upgrading again recovers. The entry's `MINOR_VERSION` equals `OPTIONS_VERSION` (2), a test pins it; a newer minor loads leniently, another major is refused. Options version 2 adds every key at its default and keeps what was stored, which `from_options` judges. The schema migration runs while any record or `blueprint_schema` is older than the shipped schema, so failures retry at every start; a hand edited blueprint stops it and reports nothing as failed; old inputs are read from the file. D28 lives in maintenance behind one manager primitive (`async_delete_routine`); the index rebuild and the summary refresh are manager primitives. |
| Consequence | Plan Section 4.2 store, migration and maintenance rows carry the landed names; lane 5 implements `MaintenanceTarget` and `SchemaMigrationTarget`. |
| PRD register entry | no |

## 2026-10-18 L43: what the summary reads of a routine, and where ownership is judged

| Field | Content |
| --- | --- |
| Context | Lane 7 found that core 2026.10 keeps a blueprint automation's rendered config as the entity's `raw_config`, inputs substituted and `use_blueprint` dropped, so `markers.is_owned(raw_config)` is false and `is_detached(raw_config)` true for every owned routine. The `RoutineSummary` contract also carries no next action with its verb and no settings. |
| Options | Ownership from `raw_config`, from the file entry, or from the entity's blueprint block; for the routine's next action, a new contract field or the summary decompiling the owned automation's inputs. |
| Choice | Ownership is judged on the `automations.yaml` entry (`async_read_automation`) or on `{**raw_config, "use_blueprint": blueprint}`, with `ha_adapter.automation_blueprint` reading the entity's blueprint block (a private attribute, so the adapter falls back to the public `blueprint_in_automation` path and reads the inputs as absent if it moves; the read capability now probes that helper). The summary decompiles the owned automation's inputs for the routine's own actions (active state verb, the next action after a skip, window conflicts) instead of a new field; for up to two seconds after a write, before the debounced rebuild, it reads the previous inputs. Invalid and missing target read "Routine off"; a paused, skipping or off routine's state wins over an earlier hand written action. |
| Consequence | Plan Section 4.2 summary and adapter rows annotated. Lane 5 judges ownership on the file entry in sync back and in the reconcile scan, calls `set_routine_provider` at setup and `async_refresh_device` after every change and after reconcile. A4 may add an optional `next_action` to `RoutineSummary` if the duplication bites. |
| PRD register entry | no |

## 2026-10-18 L44: the manager's runtime state, entities and edges

| Field | Content |
| --- | --- |
| Context | Lane 5 built the RoutineManager before the device page platforms exist (wave A3). The blueprint reads the integration's own Manual override switch and Paused until datetime, whose entity ids must be known at the first write; TECH_SPEC 4.1 leaves the result types, the patch type, who turned a routine off, the debounce start and several opt in and take control details open. |
| Options | Entity ids from the platforms when they add the entities, or pre registered registry entries; runtime state in the entities or in the manager; the debounce from the first or the last change; for "who turned it off", memory or the Store. |
| Choice | The manager is the source of truth for each routine's runtime state and pre registers the two entities at opt in (unique ids `device_routines_<device id>_manual_override` and `_paused_until`, suggested object ids from the device slug); lane 8's platforms claim them, render the view and hand restored values back through `async_restore_runtime`. Result dataclasses for every method, `ServiceValidationError` with a translation key as the only exception; the patch is a mapping of `RoutineSettings` field names. The debounce runs one second from the last change and flushes on opt out and unload. Invalid edits keep the old `last_hash`, so every later sync detects them again. Take control drops the owned record; "create a new routine" takes the first free `markers.automation_id(f"{device_id}#{n}")` from n = 2, and the summary ties an owned routine to its device by the `device_id` input. A routine the manager turned off comes back on only if the manager turned it off; a person's disable sticks (kept in memory for now, A4.0 carries persisting it). The system user is created at the first helper, not at setup. The deleted `Routines` label is recreated and re applied, never opting anyone out. A new pause replaces a skip and clears the skip's override; a restored Paused until in the past is dropped. `async_remove_entry` waits for lane 10. |
| Consequence | Plan Section 4.2 manager and entities rows carry the landed API; lane 8 drops the test shim; plan A4.0 lists the carry overs. `tests/conftest.py` gives every test its own config directory, because setup installs the blueprint. |
| PRD register entry | no |

## 2026-10-18 L45: shared modules in wave A3

| Field | Content |
| --- | --- |
| Context | The eight lanes of wave A3 run in parallel, and several need small additions to modules other lanes own: `config_flow.py` (lanes 10 and 14), `manager.py` (lanes 8 and 14), `summary.py` (lanes 11, 12 and 14), `__init__.py` (lanes 9, 10, 12 and 15), `ha_adapter.py` (lanes 10 and 14). |
| Options | Serialize the lanes that overlap, or let each add a separate, additive piece and resolve the overlaps at rebase. |
| Choice | Additive pieces, each owned by one lane, listed in plan Section 4.5's arbitration paragraph; the orchestrator rebases in landing order. The AI disclosure is a `strings.json` description, not code in `config_flow.py`. |
| Consequence | Lanes keep parallel; rebases may need a by hand merge in `strings.json` and the shared modules, which the orchestrator does and reruns the whole suite after. |
| PRD register entry | no |

## 2026-10-18 L46: action targets and responses

| Field | Content |
| --- | --- |
| Context | TECH_SPEC 4.6 asks for a native target "filtered to this integration". The devices a routine drives belong to other integrations, and this integration's entities sit on its own linked device records (L25), so an integration filter would offer only those records and the hub, which the manager ignores, and would hide a label a person puts on their own device (S13). The spec's `ignored` lists "device id, reason"; the datetime selector sends a time without an offset. |
| Options | An integration filter, or a domain filter over the supported domains plus `automation`; `ignored` as device id and reason, or the dataclass fields; an offset free `until` as UTC or local. |
| Choice | The five routine actions take a target filtered by entity domain (`domains.SUPPORTED_DOMAINS` plus `automation`, pinned by a test), with no device filter; `ignored` serializes as `{target, kind, reason}` (for a device, `target` is the device id), the asdict convention of TECH_SPEC 4.7; an offset free `until` is local time; `maintenance` takes an optional `dry_run`; a call with no loaded entry raises the translated `not_loaded`. `services.action_response` and `services.maintenance_response` are public so the WebSocket commands answer in the same shape. |
| Consequence | Three manager gaps go to plan A4.0: a past `until` or zero `for` must be rejected before target resolution (a strict xfail pins it), linked device records must resolve to the user's device, and maintenance errors must be translated. |
| PRD register entry | no |

## 2026-10-18 L47: the integration triggers and conditions

| Field | Content |
| --- | --- |
| Context | Lane 13 built FR-R17 on the V13 shape. Open: the target filter, what paused and active mean, how `all` counts routines that are off, an empty target, and whether a status change without a manager event fires. |
| Options | As chosen, or the core's conventions for its own purpose specific triggers (which leave unavailable entities out of `all` and treat `all` over nothing as true). |
| Choice | Targets filter by entity domain (the supported domains, pinned to `SUPPORTED_DOMAINS` by a test), for the reason of L46. Paused means status `paused` or `skipping` (a skip pauses until its paired end, D18 and D19); active means status `active`. `all` is strict: off and broken routines count, so `paused` with `all` fires exactly when `is_paused` with `all` becomes true; an empty target is false for both `any` and `all`. `paused` fires on every manager paused event, a replaced or extended pause included; an off routine fires neither `paused` nor `resumed`; a status change without a manager event fires nothing. No `for` option (the PRD lists only behavior). Floor targets work through `resolve_targets`; without a loaded entry nothing fires and every condition is false. |
| Consequence | The linked device record gap of L46 also affects these pickers (A4.0); the editor's picker look stays owner item O4. |
| PRD register entry | no |

## 2026-10-18 L48: Repairs fix flows and the conflict issue

| Field | Content |
| --- | --- |
| Context | Lane 11 completed the TECH_SPEC 4.8 catalog. Open: how a fix flow reports a fix that did not take, how fine grained the `conflict` issue is, whether `schedule_blocks_needed` survives a restart, where the non fixable issues link, and gaps found in the manager. |
| Options | Let the core delete an issue when its flow finishes, or abort when the problem remains; one conflict issue per pair, or per routine; persistent or not. |
| Choice | Each fixable issue has one confirm step and one manager call; a call that raises, or a fix that leaves its issue open, aborts `not_fixed` and keeps the issue (the core would otherwise delete it on finish); a missing entry aborts `not_loaded`. `conflict` is one issue per routine (subject the automation id, L41), naming every colliding automation, raised only for a routine against another automation in the same minute while Raise conflict repairs is on, and cleared statelessly. `schedule_blocks_needed` is persistent, because its cause is seen once; it clears when the helper gets blocks, from a state listener or at reconcile. Links use `homeassistant://config/helpers` and `homeassistant://config/automation/dashboard`; `adapter_incompatible` links to the guide's Troubleshooting section. The manager now clears every per routine issue except `detached_routine` on detach, and every per routine issue on cleanup. |
| Consequence | Lane 10's removal deletes every issue of the integration, the persistent one included (told); lane 15 writes the `## Troubleshooting` heading (told). Two small manager gaps go to plan A4.0. |
| PRD register entry | no |

## 2026-10-18 L49: the WebSocket API's edges

| Field | Content |
| --- | --- |
| Context | Lane 12 built the console contract of TECH_SPEC 4.7. Open: the error shape, how a subscription survives the entry reload a settings change causes, who emits `settings_changed`, what `schedule/today` lists, and who may list devices. Lanes 9 and 12 also each added an `exceptions.not_loaded` string, which the rebase kept twice. |
| Options | As chosen, or the core's generic error handler (which logs each refused setting as an error) and per entry subscriptions that end at a reload. |
| Choice | Errors carry the translation key as `code` with domain, key and placeholders (a setting problem adds a `setting` placeholder), sent directly. Subscriptions live at the hass level and re attach to the current entry's manager on a dispatcher signal sent by `async_register`, which runs before the manager starts, so the first reconcile's events arrive; the subscription itself emits `settings_changed` when it sees new settings after a reload; commands answer `not_loaded` during a reload. `settings/set` validates, merges, answers, then reloads only when the options changed; `settings/get` reads the stored options. `devices/opt` needs admin for every op, as PRD 7.5 lists. `target: all` is refused with `target_all_reserved` (D24). `schedule/today` lists the local day's actions, the earlier ones as planned, without routine actions a pause skips or actions of automations that are off, with a conflict flag computed minute by minute. The two `not_loaded` strings are merged into one, and `tests/test_repository.py` now refuses duplicate keys in every translation, icon and phrase file. |
| Consequence | `docs/api.md` documents every command from the test payloads. Plan A4.0 carries the missing `schedule_changed` for hand written automation edits. |
| PRD register entry | no |

## 2026-10-18 L50: Health and diagnostics for routines

| Field | Content |
| --- | --- |
| Context | Lane 15 completed Health and diagnostics. TECH_SPEC 10.3 lists `blueprint_status` as ok, modified or missing and asks for `degraded` on an adapter fallback; the manager reinstalls a missing blueprint in the same check that would see it, and the adapter has no fallback path to report (D2(b) is not built). |
| Options | Keep the spec's wording and leave the attributes unreachable, or report what exists and defer the rest. |
| Choice | `blueprint_status` reads `ok`, `modified`, or null before the first check (and while the adapter is incompatible, because reconcile stops before the blueprint step); `missing` never appears, because a missing file is reinstalled at once. `degraded` on a modified blueprint, `loaded_count < owned_count` (so a broken automation shows before the next reconcile raises `automation_load_failed`) or an open `automation_load_failed`; `error` on an incompatible adapter; issues a person resolves (invalid inputs, detached routine, conflict) leave Health `ok`. A `HealthMonitor` keeps the report current from manager events and this domain's issue registry updates; the Phase 1 deploy attributes are unchanged, so the deploy tool's post restart check still works. Health reads `ok` while Home Assistant boots until the first reconcile. Diagnostics report the Store as counts, owned records as numbered shapes (ids and names redacted, entity inputs `unused` or redacted), runtime state as flags, device diagnostics for the hub and for a linked record, and a final pass redacts anything matching the privacy patterns, any IPv4 address included. |
| Consequence | The adapter fallback rule is deferred (plan A4.0) until the adapter reports a fallback. The user guide adds Settings and Daylight saving nights sections; the F6 notes point at L1, L26 and L30. |
| PRD register entry | no |

## 2026-10-18 L51: the flows and removing the integration

| Field | Content |
| --- | --- |
| Context | Lane 10 built the suggestions step, the options pages and removal. Open: how the setup flow reaches the suggestions screen, how the device picker is limited to eligible devices, what a kept routine reads from after removal, and what removal cleans up. |
| Options | The core's device selector or a select built from `eligible_devices()`; kept automations reading their old override and Paused until entities, or the sentinels; ownership on removal from the Store or from the file markers. |
| Choice | Setup chains to the options flow's `suggestions` step through the core's `async_on_create_entry` and `next_flow`, only when there is something to suggest. The options flow is a menu of Settings, Devices with routines and Suggested devices; the device picker is a select of `eligible_devices()` prefilled with the opted in set; the settings page holds every PRD 10.4 key, validated by `settings.validate`, and stores the full normalized catalog. Removal decides ownership from the file markers: keep renders each owned automation the way the editor's Take control does (`ha_adapter.async_take_control_config`) with the override and Paused until inputs set to the sentinels (a reinstall would otherwise hand those entity ids to new entities the old automation would read) and writes it with `async_release_automation`; delete removes each owned automation and the timer and schedule helpers carrying the `Routines` label. Both then remove the blueprint when the file no longer uses it, the system user (only a system generated user named Device Routines), the label and the category when nothing carries them, every Repairs issue of the integration and the Store; every step logs its own failure and the rest still run. |
| Consequence | S8 is proven in the harness (kept automations fire at their times after removal). The user guide's removal and settings sections are checked against the landed tests. |
| PRD register entry | no |

## 2026-10-18 L52: the device page controls

| Field | Content |
| --- | --- |
| Context | Lane 8 built the device page platforms on the manager. Open: the time entities' wording per domain, where an unavailable control's reason lives (Home Assistant drops extra state attributes while an entity is unavailable), which controls an incompatible adapter disables, how Some days is chosen with one select, and what a restored runtime entity hands back. |
| Options | As chosen, or the contract's literal translation keys `on_time` and `off_time`, a state attribute, and every control unavailable on an incompatible adapter. |
| Choice | The time entities use the profile's label key as their translation key ("Turn on at", "Start at", "Open at", "Lock at"; PRD 4.2), with the unique ids unchanged. `reason` is a capability attribute. An incompatible adapter disables only the config controls (TECH_SPEC 4.2); Paused until, Manual override, Skip next and Resume stay available so the blueprint keeps reading the pause and the override. The Days select offers all five values; Some days keeps the current day set, which is chosen in the routine's automation form or by a `day_set` patch (a full week reads back as Every day, L38). Both runtime entities store the whole restored runtime, so either restores everything. `target` exists only with several candidates and follows later candidates on the next manager event; a target change to another profile adds or removes controls to match `page_keys`. Patches carry `source="entity"`; numbers are 0 to 1440 minute boxes. A person may turn Manual override on as well as off. `tests/blueprint/conftest.py` loads its sandbox platform into an already set up component (B43). |
| Consequence | The lane 5 shim is gone: the manager, sync back and reconcile tests run on the real entities. Five gaps go to plan A4.0, the countdown event first. The guide notes that a time is cleared in the automation form. |
| PRD register entry | no |

## 2026-10-18 L53: weekly schedules, the AI path and the hub Routines sensor

| Field | Content |
| --- | --- |
| Context | Lane 14 built the Phase 3 features in the service layer. Open: when the weekly schedule helper is created and deleted, what Skip next does with a schedule's blocks, exactly what the AI path sends, when and how often, and what the hub sensor counts. Integration found two overlapping ways to clear `schedule_blocks_needed` (lanes 11 and 14) and a duplicate `options.step.settings` key from lanes 10 and 14. |
| Options | As chosen; for the overlap, either mechanism. |
| Choice | Setting Days to Weekly schedule without naming a schedule creates `schedule.routine_<slug>` named "<device> routine" (FR-R2) with the `Routines` label and no device (L36), drops the times, and links it; a schedule named in a patch is linked as it is; Days back keeps the helper and its blocks, and choosing Weekly schedule again relinks it; the D28 cleanup and a routine deleted by hand delete the own helper only while it is a labeled schedule helper; a failed creation keeps the patch out with `schedule_helper_failed`. Skip next outside a block reads the blocks through `ha_adapter.async_schedule_blocks` and skips the next block start with its end (D18, Paused until at the end plus one minute); blocks that meet count as one (A6); inside a block the end is skipped alone with the override (D19). The AI path is off until an AI Task entity is chosen; after each index rebuild it queues hand written automations with an unread line, keyed by config hash, and sends one per `ai_task.generate_data` call: the trigger, condition and action blocks as written, templates included, entities by entity id, devices, areas, floors and labels as numbered placeholders, no aliases, descriptions, states or names; never in the first five minutes after the coordinator starts; a sliding hour token bucket at `ai_calls_per_hour` with one point in time listener; answers trimmed to twelve words, cached in `ai_cache`, shown as "<text> (AI)" with `source: ai`; a failure is not retried for that hash. The hub Routines sensor counts `active` routines and lists every owned or detached routine. For the overlap, a schedule's `next_event` (which the core sets only when it has blocks) clears the issue whatever the block list answers; the settings step holds one `ai_task_entity` description, the AI disclosure. |
| Consequence | The duplicate key test now guards every JSON file. Plan A4.0 keeps one clearing mechanism and carries four smaller gaps. The quality scale's remaining todo rules are `action-exceptions` (A4.0) and `brands` (Build B). |
| PRD register entry | no |

## 2026-10-18 L54: wave A4 runs as four lanes

| Field | Content |
| --- | --- |
| Context | Plan Section 4.6 gives wave A4 to the orchestrator with one optional lane for the simulation. Waves A1 to A3 left a long carry over list (A4.0), and A4.1 to A4.3 touch disjoint files (a new contract test file, a new simulation test file, the parser grammar and the golden corpus). |
| Options | Serial work by the orchestrator, or four parallel lanes with A4.4 and A4.5 kept by the orchestrator. |
| Choice | Four lanes. The contract and simulation lanes never edit the service modules the carry over lane owns: a defect they find is pinned as a strict `xfail` and routed. Two carry over items move to Build B because they have nothing to act on before schema 2 or D2(b). |
| Consequence | Plan Section 4.6 amended; the Status line names the lanes. |
| PRD register entry | no |

## 2026-10-18 L55: G5 is met as written after four zero guessing grammar additions

| Field | Content |
| --- | --- |
| Context | Finding F3: G5 asks that at least 90 percent of the golden corpus is parsed, with zero wrong lines. At the Phase 1 exit the corpus parsed 45 of 56 items (80.4 percent), recorded as a pass. Task A4.3 classified the 11 unparsed items: 4 stopped on `event.received`, 1 on an event trigger on the timer's own `timer.finished` event, 2 on state triggers listing several states, 3 on an integration defined device trigger with no entity, 1 on a custom event. "Parsed" is what `tests/golden/test_lines.py` counts: an item (one line per automation, device and action) whose source is the parser, partial lines included. |
| Options | (a) Keep G5's measure as written, every item in the denominator; (b) count golden negatives separately; (c) add synthetic fixtures to raise the rate (rejected: it measures nothing). |
| Choice | (a). The zero guessing rules (L29) added in A4.3 bring the corpus to 51 of 56 (91.1 percent) with no wrong line; every changed golden line was reviewed. Golden negatives are defined by construct, not by which home logic they belong to: an item whose every trigger means something only a guess could say (an integration defined device trigger with no entity, a custom event, a template, a webhook): today 4 items in two fixtures; 51 of the 52 others parse (98.1 percent). The remaining unparsed item, a trigger from unknown or unavailable with a filter that drops them, is refused on purpose. The golden test's floor is 90 percent. |
| Consequence | Grammar, each rule with unit tests: several states in a state trigger's `to` or `from` read as one trigger per state, pairs that cannot fire left out; the unknown and unavailable filter is noise only for a trigger about real states; an event trigger on `timer.started`, `timer.finished` or `timer.cancelled` whose `event_data` names one timer reads as the timer trigger; `event.received` reads with its event types (new phrase `when_event_received`, `NamedTrigger.values`); purpose specific triggers read only targets of their own domain and only the default behavior, and `vacuum.docked` becomes the core's `vacuum.returned_to_dock`. FR-S2 carries a note. Owner log O14 stays open only as a veto on the additions. |
| PRD register entry | no |

## 2026-10-18 L56: what the contract tests and the 30 day simulation pin

| Field | Content |
| --- | --- |
| Context | Tasks A4.1 and A4.2 ran against everything built in waves A1 to A3. A4.1 needed an exact form of rule P16 to test; A4.2 found that TECH_SPEC 6 promises a full rebuild of the Store that cannot include the inputs before a schema migration. Both lanes pinned defects as strict xfails rather than fixing service modules another lane owned. |
| Options | Weaken a rule until the code passes, or pin each violation; amend TECH_SPEC 6 or invent a way to rebuild `previous_inputs`. |
| Choice | P16 as tested: a surface (the platforms, `entity.py`, `services.py`, `websocket_api.py`, `trigger.py`, `condition.py`, `repairs.py`) imports only types, constants and named entry points of this integration, reaches the manager only through public `RoutineManager` members and the summary only through its read API, holds no status or settings rule, and every entry point reaches the service layer; direct core calls are not policed (two remain: registry cleanup in `entity.py` and the options write in `settings/set`, L49). PRD 12's round trip is pinned at both ends: through the manager it already holds; the summary reading a routine without the manager's item must read the inputs, not the rendered blueprint. The simulation runs 30 days (2026-11-02 to 2026-12-02, no DST change) over three routines with every scheduled change checked to the second (214 changes), 274 sentence checks, two cold starts carrying S3, S4, S5 and S12, an update over a fake schema 0 on day 14 done as an in place entry reload, and a final Store rebuild compared with the kept one. TECH_SPEC 6 now lists `previous_inputs` with `opted_out_at` and `ai_cache` as not rebuildable. |
| Consequence | Fourteen defects go to the carry over lane: availability, status rules and a cross surface import in four surfaces; the summary's reading of an owned routine and of a taken over one; an aware time held by the manager; midnight rewording of day relative states; a started listener removed twice; a sync pass racing a write; removed entities still hearing events; a rebuild that loses `blueprint_schema` and `alias_history`; Health stale after a cleanup; the linked device record keeping the old name. |
| PRD register entry | no |

## 2026-10-18 L57: the carry over fixes and Store minor version 2

| Field | Content |
| --- | --- |
| Context | Task A4.0 closed 29 items: the carry overs of waves A1 to A3 and the 14 defects A4.1 and A4.2 pinned. Several needed a design choice: persisting why the manager turned a routine off, finding a kept helper after a rename and a restart, where the routine's lines come from when the summary reads an owned automation, and how settings are held in memory. |
| Options | Re derive the off reason at reconcile, or persist it; find kept helpers by slug, or record them; read the rendered blueprint, or the inputs. |
| Choice | Store minor version 2 adds `suspended` (automation id to `invalid` or `missing_target`; a target that returns or inputs corrected during a restart turn the routine back on, a person's disable sticks, opting out forgets it) and `own_helpers` (device id to every timer and schedule the manager created, linked again, renamed with the device and deleted by cleanup, a hand deletion and the delete removal); `migrate_store` fills both from 1.1, and `rebuild_index` rebuilds `own_helpers` but not `suspended`. PRD 12's round trip now reads the inputs: the summary indexes `nextrun.routine_lines(decompile(inputs))` for an owned automation (`routine_lines` and `routine_verbs` moved to the pure `nextrun`), and a taken over routine reads with the detached kind while the manager says detached. The manager holds `compiler.canonical(merged)`; a patch naming `day_set` without `days` means Some days. `RoutineView.is_paused` and `is_active` are properties (payloads unchanged) over `models.PAUSING_STATUSES`; `unavailable_reason(device_id, key)` answers for `skip_next` (`nothing_to_skip`), `resume` (`not_paused`) and `turn_back_on_after` (`schedule_off` while the window or weekly schedule says off), and a missing target leaves the target select available. Turn off after reads "Close after" and "Lock after" (`DomainProfile.off_after_label_key`). The manager follows each routine's timer and fires `routine_changed` (Skip next during a countdown, D19); emits `schedule_changed` a second after any Schedule change (hand written edits included); uses `async_at_started`; re reads an entry under the routine's lock in sync back; flushes the Store on stop; names the linked device record after the device (`name_by_user or name`). The summary wakes at the earlier of the next change and local midnight. Maintenance raises translated `maintenance_failed` errors (quality rule `action-exceptions` done) and owns the removal logic (`maintenance.async_remove_integration`). Only `next_event` clears `schedule_blocks_needed`. A skipped weekly block keeps the block after the skip in memory (stale until the skip ends if the blocks are edited meanwhile). |
| Consequence | TECH_SPEC 6 lists the two fields and what cannot be rebuilt. The user guide notes Close after and Lock after, the new unavailable reasons and that a day set alone means Some days. Diagnostics do not yet count `suspended` and `own_helpers` (Build B). A wall clock dependent Stage 0 test (`test_v12_datetime.py`) failed near local midnight because a timestamp sensor is compared by time of day only; it now runs at a fixed instant. |
| PRD register entry | no |

## 2026-10-18 L58: auto deploy stays off after the Build A exit

| Field | Content |
| --- | --- |
| Context | Plan Section 0.1.6 has the orchestrator turn auto deploy back on after deploying the beta tag by hand at a build exit, and also says the switch is off while a build is open. Build B opens right after the Build A exit, and its pushes move `dev-stable`, which the auto deploy would write to the instance's disk before the owner's restart R1 loads the beta. |
| Options | (a) Turn auto deploy on as written; (b) keep it off and move the instance only by hand deploys of tags. |
| Choice | (b). The instance moves only by hand deploys of tags: the beta at a build exit, the full tag after its live validation (Section 5.4), until the last build is released and the owner decides the channel (O13). The post restart check, the last good commit and the rollback stay as they are (L13, L16, L17). |
| Consequence | Plan Section 0.1.6 amended. `v0.3.0-beta.1` (`efbf757`) is on disk since 2026-10-18 07:31Z and R1 loads exactly it; owner log O15 carries the request with the hazard (no diagnostics, Repairs or options of Device Routines before the restart). |
| PRD register entry | no |

## 2026-10-18 L59: Build B opens with wave B1 as three lanes; restart R1 has happened

| Field | Content |
| --- | --- |
| Context | The Build A exit is recorded (Status line, L58). Health reads `ok` on `efbf757` (`v0.3.0-beta.1`, blueprint schema 1, no routine) since about 15:16Z: the owner's restart R1 happened before Build B opened, and auto deploy reads off. Plan 6.2 gave lanes 16 to 18 one line each. Lanes 16 and 17 change two sides of one tested contract: `tests/integration/test_contracts.py` compares the compiler's input names, defaults and schema with the installed blueprint and with the blueprint tests' mirror, so each lane alone breaks those tests. |
| Options | (a) Lane 16 first, lane 17 after it lands; (b) both in parallel against a pinned contract, the comparing tests failing by design in each worktree until both land. |
| Choice | (b). Plan 6.2.1 pins the shared names, the 38 schema 2 inputs with their order, defaults and value types, and the blueprint semantics; 6.2.2 to 6.2.4 are the lane briefs. Each lane reports the comparing tests by id; the orchestrator lands lanes 16 and 17 together, and any other failure is the lane's. Lane 18 is independent. Live validation A (plan 5.3) runs in its own session, proposed to the owner; this session does not run it and does not touch the validation records. Auto deploy stays off (L58). |
| Consequence | Plan 6.1 amended by L60 and L61; plan 6.2 expanded; the Status line names the lanes and their branches. Owner log O15 is done. |
| PRD register entry | no |

## 2026-10-18 L60: sun bounds are a kind and an offset per side, compiled into blueprint input schema 2

| Field | Content |
| --- | --- |
| Context | Plan 6.1 sketches FR-R10 as blueprint schema 2. Open: the shape in `RoutineSettings`, the offset's unit and range, whether a window with a sun bound crosses midnight, how the blueprint tests a window with offsets, and how schema 1 inputs read once the compiler is on schema 2 (`migration.DECOMPILERS` is empty, so `decompile_inputs(inputs, 1)` would refuse every routine at the first load). |
| Options | Shape: (a) a kind and an offset per side next to the existing times; (b) one bound type replacing `on_time` and `off_time`, which every caller of Build A reads. Crossing: (c) a fixed nominal time per sun event; (d) the real sun times of the day, which would make the derived inputs change with the seasons and break `compile(decompile(i)) == i`. Window test: (e) the `sun` condition per half; (f) the state of `sun.sun`, which carries neither offsets nor the per half weekday sets. Schema 1: (g) a copied schema 1 decompiler; (h) `compiler.decompile` behind a schema 1 key check, pinned by a recorded fixture. |
| Choice | (a), (c), (e), (h). Offsets in whole minutes (minutes everywhere, as for every other duration), plus or minus 180, so a nominal sun time plus its offset stays inside one day. Nominal sunrise 06:00 and sunset 18:00 decide only whether a window crosses midnight and which days its end runs on: sunset to sunrise crosses, sunrise to sunset does not, 22:00 to sunrise crosses, sunset to 23:00 does not. The four sun triggers share the ids `scheduled_on` and `scheduled_off`, so pause, skip, the start and end day rule and the skipped event apply to them unchanged. `expected_on` tests each half with the `sun` condition and its offset, Home Assistant's documented form for a window across midnight; the 6.1 sentence about `sun.sun` is superseded. Every new input defaults to schema 1 behavior, so a schema 1 routine runs unchanged on the schema 2 blueprint between the blueprint install and its rewrite. `DECOMPILERS[1]` refuses schema 2 keys and otherwise reads with `compiler.decompile`; `tests/fixtures/schema1/inputs.json` pins it, and a later change that reads schema 1 differently freezes a copy then. |
| Consequence | A fixed bound that a sun bound passes over in the course of a year (sunset to 20:00 in a northern summer) follows the nominal order; the user guide says so (wave B3). On a day without a sunrise or sunset `nextrun` leaves that bound's action out. Plan 6.2.1 carries the contract; TECH_SPEC 3.1, 3.3, 3.6 (lane 16) and 5 (lane 17) follow. |
| PRD register entry | no |

## 2026-10-18 L61: what an exact conversion match is

| Field | Content |
| --- | --- |
| Context | Plan 6.1 gives `conversion.match(lines, device)` and two shapes. The parser's lines are one per action on the device, so an extra notification or scene in the same automation is invisible to them, and converting would drop it. A window crossing midnight with a weekday condition ends on the condition's weekdays in a hand written automation but the day after each start day in a routine (FR-R1: a window belongs to the day it starts on). |
| Options | Match on the lines only; or on the whole config, with the parser for what the lines say. |
| Choice | `match(config, device)`. FR-R1 shape: exactly two enabled `time` triggers at fixed whole minute times (no entity, no offset), at different times; exactly one on action and one off action, on one entity of the device, each run by exactly one of the two triggers (a `choose` or an `if` on `trigger` conditions naming their ids) and carrying nothing beyond the target; conditions none, or only a `weekday` (a `time` condition with `weekday` alone, or the same `weekday` on both triggers); a window crossing midnight matches only on every day. FR-R3 shape: exactly one enabled `state` trigger on one entity of the device, `to: "on"`, `from` absent or `"off"`, `for` a whole number of minutes from 1 to 1440; exactly one off action on that entity; no condition. Everything else is None: a template, variables, a second entity or device, any other action (a delay, a notification, a scene, a toggle), a disabled trigger or action, an action carrying data (a brightness), seconds, an entity held time, any other condition. The settings carry the entity, the times or the duration and the days (a named day set as its name, else Some days); every other field is the `RoutineSettings` default. |
| Consequence | Lane 16 implements and tests every shape and exclusion; lane 20 validates a match against the profile, skips devices with a routine, applies the global defaults and counts the golden corpus's offers by fixture number. |
| PRD register entry | no |

## 2026-10-18 L62: where the console's source, bundle and words live

| Field | Content |
| --- | --- |
| Context | Plan 6.1 fixes Lit, TypeScript, Vite and vitest and records the committed bundle when it is reached. Open: where the source and the bundle live, what the scaffold lane commits, where the console's words come from, and how the views are tested before the integration serves them (lane 21). |
| Options | Source inside the integration or at the repository root; the bundle committed from the scaffold on, or once the panel and its CI check exist; console words in `strings.json` (whose categories are fixed by the core) or in the console. |
| Choice | Source in `frontend/` at the repository root, so the release zip and the dev channel carry only the bundle; the bundle at `custom_components/device_routines/frontend/dist/device-routines-panel.js`, inside the deploy tool's `frontend/` prefix (a browser reload); uncommitted in wave B1 and committed by lane 21 together with `panel.py` and the `frontend` CI job, which records the 6.1 decision. The console's words are keys in `frontend/src/translations/en.json`; error codes render with the integration's `exceptions` translations through `hass.localize`; colors from the theme variables; no `ha-*` element is needed. The scaffold is tested with vitest against a fake `hass` whose connection answers with the JSON examples of `docs/api.md`, extracted into `frontend/test/fixtures/api.json` by a script, and a test keeps the two equal. |
| Consequence | Lane 18 commits no bundle; `.gitignore` keeps `dist/` ignored until lane 21 adds the exception. The style and privacy checks cover the frontend's text files. |
| PRD register entry | no |

## 2026-10-18 L63: the console scaffold's choices, and four API gaps for wave B2

| Field | Content |
| --- | --- |
| Context | Lane 18 built the console scaffold (plan 6.2.4) against the recorded payloads of `docs/api.md`. Open: the Lit style, what renders and refreshes, routing, where names and times come from, which settings are edited inline, the dependency pins, and what the console needs that the API does not give. |
| Options | As chosen; for each gap, work around it in the console or extend the API. |
| Choice | Lit 3.3.3 without decorators (`static properties` and `declare` fields), TypeScript 7.0.2, Vite 8.3.2, vitest 5.0.3 with happy-dom 20.14.5, every version exact and the lock resolved with `npm install --before` two weeks back. Only the open view renders; a `subscribe` event refreshes only that view, and a view reads everything again when it opens. Tabs push `<panel>/<view>` and fire `location-changed` as the core's navigation does; links are real anchors. Device and area names come from `hass.devices` and `hass.areas`, else the id. The inline routine editor covers the target, the times, Days and the day set, the weekly schedule, the three minute numbers and the three flags; pulse and Only when stay in the automation form. Settings use a catalog of the PRD 10.4 keys; maintenance always previews with `dry_run` first. Unknown enum values are shown as sent. The console's own time cells follow `hass.locale.time_format` for now. The fixture is keyed by `docs/api.md` section and regenerated with `npm run extract-fixture`. Gaps, carried to wave B2 rather than worked around for good: (1) RoutineView has no `opted_in`, so an opted out routine waiting for cleanup looks like an opted in routine that is off; (2) `schedule/today` items carry no device name or automation alias; (3) `docs/api.md` lacks JSON examples for `devices/opt` `list` and `out` and for the success answers of `routines/get`, `routines/set` and `settings/set`; (4) the `ignored` entries of `routines/action` carry a reason key without placeholders. Also for wave B2: the console's time cells should follow the integration's `time_format` setting, `auto` meaning the user's locale, so they match the sentences. |
| Consequence | Wave B2 assigns the gaps with the file ownership of its lanes. The bundle stays uncommitted until lane 21 (L62). |
| PRD register entry | no |

## 2026-10-18 L64: sun bound edges settled by lanes 16 and 17, and their integration

| Field | Content |
| --- | --- |
| Context | Lanes 16 (pure core) and 17 (blueprint schema 2) built FR-R10 against plan 6.2.1 and L60 and landed together. Open: where each problem is reported, the offset text forms, the arithmetic of a sun instant, how the blueprint switches the time and sun halves, what the core's `sun` condition and trigger really do at the edges, and what integration needed beyond the lanes. |
| Options | As chosen, or the stricter or looser variant of each edge named below. |
| Choice | Problems: a sun start on a profile without an on action is `on_time_not_supported` on `on_kind` (a time keeps `on_time`); an end at sunrise or sunset is valid on every profile (Lock at sunset); two equal sun bounds are `same_on_and_off_time` on `off_sun_offset_min`; equal means the same kind with the same time or offset, so sunset with 18:00 is valid and does not cross midnight; the offset range is checked on every routine. Offset text: `decompile` reads one or two hour digits, an optional `+` or `-` and optional seconds, dropped toward zero. A sun instant is that day's event in the local zone plus the offset on the wall clock, the arithmetic the parser's sun lines already used; it differs from the core's absolute arithmetic only when a daylight saving change falls between the event and the offset. `expected_state` needs a sun time only for a half that applies today, takes crossing from `crosses_midnight`, strips a zone from a time and reads invalid equal time bounds as a same day window. `late_window_end` of a sun start stays the sentinel time plus the window; the blueprint uses `late_sun_offset`, one `sun` condition with `after` and `before` on the same event. In the blueprint each half's time alternative is switched by its time flag, so an unset side never reads true through its sentinel. Core facts: the `sun` condition counts the instant of a `before` bound as still before, where `nextrun` and the time condition do not, so the wave B2 test comparing `expected_on` with `expected_state` never draws an instant on a sun bound; a sun trigger carries no `trigger.now`, so the skipped event's `scheduled_at` is the moment the run started; installing a blueprint over an existing file reloads automations through the core, so lane 19 sets up `automation` before it installs. Only when gates every start, the catch up at a pause end and the other on paths but not a scheduled end, and a start it blocks fires no skipped event, as Build A built it; the user guide says so (wave B3). `migration.DECOMPILERS[1]` is `decompile_schema_1` over a frozen `SCHEMA_1_KEYS`, pinned by 120 recorded cases; the schema 1 blueprint file is kept as a fixture pinned by its sha256 for lane 19. Integration: the contract tests' selector check knows a single select, the mirror comparison carries sun bounds, the derived properties count as settings in the P16 rule, the manager accepts the four fields in a patch (the rest of the manager's sun support is lane 19), the console fixture is regenerated from `docs/api.md`, and `parser.parse_duration` now reads a period no `timedelta` holds as not understood (lane 16's property test found that one such hand written automation stopped the summary). |
| Consequence | TECH_SPEC 3.1, 3.3, 3.6, 3.10, 5 and 11.2 carry the lanes' text. Until lane 19, a sun bound set through a patch runs in the blueprint, but the manager's catch up and override decisions see no window for it (they pass no sun lookups yet). On a day the sun does not rise or set, and at high latitudes where sunset plus the offset passes midnight, the nominal order stands (L60). |
| PRD register entry | no |

## 2026-10-18 L65: the conversion match's exact forms

| Field | Content |
| --- | --- |
| Context | Lane 16 implemented `conversion.match` to L61. Open: which domains each shape covers, which action and trigger forms count as exact, and which config keys an exact automation may carry. |
| Options | Accept every form the core accepts, or only forms whose meaning is certain; a narrower match costs offers, never a wrong one. |
| Choice | FR-R3 matches only switch, light, fan, input_boolean and humidifier (a climate entity is never "on", a media player has several active states). FR-R1 actions are exactly the profile's on and off actions (`homeassistant.turn_on` does not match). Forms: a `choose` of exactly two options and no default, one `if` with `then` and `else`, or two `if`s without `else`, each naming exactly one trigger id; trigger ids are text, the core's default index ids included; `at` is one text time with zero seconds; `to` is the text "on" and `from` absent or "off"; weekdays on the triggers together with a weekday condition match only when the condition lists every day; any `enabled` other than true and any `continue_on_error` give None; top level keys beyond the sections are only `id`, `alias`, `description`, `mode`, `max`, `max_exceeded`, `trace` and `initial_state`; a config naming both the singular and the plural of a section gives None; the target is `target.entity_id` naming one entity of the device. |
| Consequence | The target rule is narrower than the parser, which also reads `entity_id` on the action and in `data`: lane 20 widens it to the parser's forms, each with a test, if the golden corpus or common hand written automations show those forms, and counts the offers by fixture number either way. |
| PRD register entry | no |

## 2026-10-18 L66: wave B2 runs as three lanes; who owns the shared service modules

| Field | Content |
| --- | --- |
| Context | Plan 6.2 names lanes 19 (FR-R10 in the manager and on the device page, the first load migration), 20 (conversion offers) and 21 (the console in Home Assistant). They meet in `manager.py`, `summary.py`, `websocket_api.py`, `docs/api.md` and the user guide, and the four API gaps of L63, FR-R9's Today flag and Schedule line, two Build A carry overs (the migration fix of L48, the diagnostics counts of L57) and the `expected_on` equality test of L64 need an owner. |
| Options | Serialize the lanes that share a module, or split ownership by module with one appended section where two lanes meet. |
| Choice | Parallel, with plan 6.2.5 as the contract. Lane 19 owns `manager.py`, `models.py`, `nextrun.py`, the platforms, `entity.py` and `diagnostics.py`, and takes L63 gaps 1 (`RoutineView.opted_in`) and 4 (`IgnoredTarget.placeholders`), the Schedule line of FR-R9, the L48 migration fix, the L57 counts and the equality test. Lane 20 owns `summary.py`, `repairs.py`, `websocket_api.py` and `conversion.py`, adds one section at the end of the manager class (`async_convert_automation`), and takes L63 gap 2 and FR-R9's Today flag (`DayItem.device_name`, `alias`, `conditions`). Lane 21 owns `panel.py`, the panel lines of `__init__.py`, `frontend/`, `ci.yml`, `.gitignore` and the `dependencies` of `manifest.json`, takes L63 gap 3 (the missing examples) and the console side of every gap, and builds the conversion section against the contract until lane 20's examples land. Only enabled hand written automations are offered: converting a disabled one would start a schedule nobody runs today. The original is turned off only after the routine exists, so a failure leaves it as it was. |
| Consequence | The orchestrator merges the manager section and the shared docs at rebase, regenerates the console fixture from `docs/api.md` after lanes 20 and 21 land, and adds the `frontend` check to branch protection when lane 21 lands. |
| PRD register entry | no |

## 2026-10-18 L67: conversion offers as built, and offers are not problems

| Field | Content |
| --- | --- |
| Context | Lane 20 built FR-M1 to plan 6.2.5 and L61, L65. Open: which target forms count, when offers are computed, what "has a routine" means, what a conversion copies, how the Repairs flow refuses, and whether an open offer is a problem for the hub Problem sensor and Health, which PRD 4.4 ties to any open issue. |
| Options | For the Problem sensor: count every issue as PRD 4.4 says, or leave the offers out. |
| Choice | An action names its entity in `target`, on the step or in `data`, exactly once; an empty `target`, `data` or `metadata` carries nothing, because the automation editor writes `data: {}` and `metadata: {}` on every step. Offers are computed at every view refresh, so turning an automation on or off or a new routine updates them at once, and `offer_for` reads the config again and compares its hash, so an edit inside the rebuild delay is never converted. Only automations with an entity registry entry are offered (the label lives there). "Has a routine" is an owned automation or a detached routine for the device, in the summary and the manager alike; a device only opted in is still offered. A match also needs a target a routine can drive (`pick_targets`) and the profile of its device class. A conversion copies the target, the times, Days, the day set and Turn off after; everything else is the opt in's defaults; the routine is written at once, then the original is turned off, then labeled `Replaced by routine` (`mdi:swap-horizontal`). The manager refuses with `conversion_not_offered`, `device_has_routine` or `editing_unavailable` before it changes anything; a later problem raises its own key and a failed write `conversion_failed`, leaving the device opted in and the original untouched. The `conversion_offer` issue is a non persistent warning per automation; every refusal in its flow aborts `not_fixed`. An open offer is a suggestion, not a problem: the hub Problem sensor and Health's `issues` leave `conversion_offer` out (a refinement of PRD 4.4's "any issue"). Golden corpus: 4 of 51 fixtures are offered (two Turn off after 60, one 17:00 to 09:00 window, one Turn off after 30), and every other fixture that acts on a device is named with its reason. |
| Consequence | TECH_SPEC 3.10 names the target forms. The Problem sensor and Health change lands with the wave B2 integration. A `test_contracts.py` example failed once under `-n 4` with `respect_manual` read back differently by the summary's index; it passed in every rerun and is watched at integration. |
| PRD register entry | no |

## 2026-10-18 L68: the console panel as built

| Field | Content |
| --- | --- |
| Context | Lane 21 made the console a Home Assistant panel (plan 6.2.8) and landed after lane 20. Open: the manifest dependencies, the sidebar title and the translation key rule, how the panel survives a reload, how the static path and its caching work, which Node builds the committed bundle, and how the console reads the new API fields. Integration also found that a routine's Today row repeated itself ("Routine Routine: Living room fan"). |
| Options | Declare `frontend` and `panel_custom` as dependencies, or only `http`; a translated sidebar title, or the integration's name. |
| Choice | `manifest.json` gains `http` only: declaring `frontend` makes every harness setup install the core's frontend package, and the core sets the frontend up in stage 0, before any integration, while the panel helpers it calls tolerate its absence; hassfest allows both imports. The sidebar title is the integration's proper name, "Device Routines", like the manifest name, the hub device and the entry title, because the core has no translation category for a custom panel's title; a test pins it to the manifest name and the console's `panel.title` key. The bundle is served from `/device_routines/static/` with `?v=<version>` and no long lived cache headers (a dev deploy of the same version shows after a page reload), the static path once per run under a `HassKey`; the panel's removal at unload waits for the entry's setup lock and removes it only when no entry is loaded, so a settings save that reloads the entry never makes the open console vanish. `StaticPathConfig` comes from its documented path with the component's only `type: ignore`. CI builds with Node 22, as `release.yml` does; the bundle was byte identical on Node 22.23.1 and 26.4.0 from a clean install, and the `frontend` job fails when the committed bundle differs from its build. The console reads `time_format` with `settings/get` (`auto` follows `hass.locale`), shows opted out routines in their own section with Opt in again, names an ignored target from the `device` placeholder first, flags gated Today actions "If 1 condition passes", hides the conversion section on a server without the command, and shows only the kind on a routine's Today row, because the routine's alias repeats the device the row names. The command table test seeds the documented evening lamp automation for the conversion examples. |
| Consequence | `frontend` joins `REQUIRED_CHECKS` and branch protection once its first run is green. The `routines/set` answer's conflicts lag the new settings until the debounced write (documented next to the example); lane 19 computes them from the new items. |
| PRD register entry | no |

## 2026-10-18 L69: sun bounds on the device page as built, the midnight defect, and where v0.3.0 is tagged

| Field | Content |
| --- | --- |
| Context | Lane 19 built FR-R10 in the manager and on the device page, the schema 2 first load and FR-R9's Schedule line (plan 6.2.6), and its `expected_on` equality test found a Build A defect: the blueprint's "before Turn off at" half tested `before: off_time` alone, which the core reads as the whole day for 00:00:00, so a routine ending at midnight expected the device on all of its end day (a restart, a reconnect or a cleared override turned it on). `v0.3.0-beta.1` carries it. Integration of wave B2 also settled the open points of L67 and lane 19's findings. Plan 5.4 tags `v0.3.0` "on the commit that holds the record", but `dev` carries Build B since `2c02f43`. |
| Options | For the defect: a schema change, or the same inputs read differently. For `v0.3.0`: tag a `dev` commit (Build B code labelled 0.3.0), or the validated code. |
| Choice | The off half's time alternative is `not` the time condition `after: off_time` with the end day apart: no input changes, schema 2 unchanged, every Build A row green; the equality test pins midnight as an explicit example. Device page: each side the profile has gets an advanced select "<verb> timing" (Time, Sunrise, Sunset; keys `<label>_kind`, falling back to `on_kind` and `off_kind`) and a number "<verb> sun offset" (a box, minutes, -180 to 180, keys `<label>_sun_offset`), disabled by default; `sun_bound` ("Sunrise or sunset gives this time") and `time_bound` ("A time of day is set, so no sun offset applies") make the unused control unavailable, and both read `weekly_schedule` with Days on Weekly schedule, which resets the kinds to Time unless the patch names them; a time sent alone makes its side a time, and a null time clears the side. The manager passes sun lookups over `get_astral_event_date` to every `nextrun` call. `condition_count` is set on every line the blueprint gates with `extra_ok`: starts, Turn back on after, a weekly block start and the pulse. `IgnoredTarget.placeholders` (excluded from comparison) names the device, or the target's own name, merged under a refusal's own placeholders; the action service response is unchanged. The `automation_load_failed` fix reinstalls the blueprint when needed and reruns the whole schema migration. Diagnostics count `suspended` automations and `own_helpers` helpers. The `routines/set` answer drops the conflicts the change ended at once; a conflict the change creates appears with the Schedule's next read, about three seconds later, with `routine_changed`. Integration: `repairs.problem_issue_ids` (open issues but the offers) feeds the Problem sensor and Health (L67); `nextrun.in_window` takes the core's defaults (a missing `after` is midnight, a missing `before` the end of the day), so `before: 00:00:00` alone is the whole day; the manager's routine item takes `custom_logic` from its lines, as the summary's index does. `v0.3.0` is tagged on `efbf757`, the code live validation A runs and whose manifest says 0.3.0, and `main` stays there until the Build B exit; the record stays on `dev`, and the release notes name the midnight fault as known in 0.3.0 and fixed in 1.0.0. |
| Consequence | Plan 5.4 amended. Wave B3 carries three small items: window conflicts for sun bound routines (`conflicts.find` passes no sun lookups), sun instants shown to the second in the Schedule state, and the summary reading the manager's settings so a conflict a change creates shows at once. |
| PRD register entry | no |

## 2026-10-18 L70: wave B3 runs as two lanes; the Build B deploy waits for live validation A

| Field | Content |
| --- | --- |
| Context | Plan 6.2.9 gives wave B3 to the orchestrator. Besides the exit, it holds two independent pieces of work: the three carry overs of L69 (code in `conflicts.py`, `summary.py`, `manager.py`) and the publication material (brand assets, `docs/publication.md`, README, the user guide). Live validation A (plan 5.3) is open on `efbf757` and waits for the owner's O17; deploying `v1.0.0-beta.1` to the instance's disk meanwhile would let Home Assistant lazily import Build B modules into the running beta (plan 0.1.6, known hazard) during that validation. The `frontend` check passed on Linux (`fba3eed`). |
| Options | Serial work by the orchestrator, or two lanes with the exit kept; deploy at the Build B exit as 0.1.6 says, or after live validation A records. |
| Choice | Two lanes (22 carry overs, 23 publication) as plan 6.2.9 now lists them; the orchestrator lands them and does the exit. The tag `v1.0.0-beta.1` and the fast forward of `main` happen at the exit as planned; the hand deploy waits until live validation A has recorded Section 5.3 and `v0.3.0` is tagged on `efbf757` (L69), and the R2 request (O16) follows the deploy. `frontend` was added to the required checks of `main` (read before and after). The logo's text is set in a font whose license allows it (Pillow's bundled CC0 font), and the brand assets wait for the owner's approval under O10. |
| Consequence | Plan 6.2.9 amended. The Status line names the lanes. |
| PRD register entry | no |

## 2026-10-18 L71: two live findings of validation A go to lane 22

| Field | Content |
| --- | --- |
| Context | Live validation A (plan 5.3, on `efbf757`) found two faults the harness missed. F1: deleting a routine's automation through the config endpoint or the editor fires no `automation_reloaded` (the core's delete hook only removes the entity registry entry), so sync back never runs: a deleted detached routine keeps `detached_routine` and unavailable controls, and a deleted owned routine is not reset (PRD 8.2) until some later reload or restart; the harness modeled a delete as a rewrite plus a reload. F2: a device whose automations are all turned off reads the first disabled item's summary as its Schedule state ("5:00 PM: on"), which reads as planned; FR-S4 does not cover that case. |
| Options | F1: listen for the registry removal, or poll; F2: no state, or a state that says so. |
| Choice | Both go to lane 22 (it owns `manager.py` and `summary.py` in wave B3), harness test first (rule 12). F1: the removal of an `automation.` registry entry the manager knows as an owned or detached routine requests a sync, tested through the real config view. F2: such a device reads "Automation off" with one item and "Automations off" with several (phrases `state_automation_off`, `state_automations_off`); a routine that is off keeps "Routine off". Both are fixed for 1.0.0; the `v0.3.0` release notes list them with the midnight end of L69 as known faults. |
| Consequence | The live session continues with a single id reload after a delete as a workaround. |
| PRD register entry | no |

## 2026-10-18 L72: wave B3 as built, and the Build B exit

| Field | Content |
| --- | --- |
| Context | Lanes 22 (the L69 carry overs and the live findings of L71) and 23 (publication material) landed. Open: where the minute rule for sun instants lives, how a delete in the editor is told apart from the manager's own delete, what F2 counts, the brand assets' palette, font and reproducibility, what the README links to, and what the exit tags. |
| Options | As chosen. |
| Choice | `conflicts.find` takes the summary's sun lookups; `RoutineSummary.settings` (appended) lets the summary read a routine's rows, conflicts and Today items from the manager's settings, so the interim conflict filter of L69 is gone. The minute rule lives in the summary (`sun_marks`, `stated`): an instant that equals a marked sun event plus its offset reads to the whole minute in the state, the skipped form and the hub's next action, while every computed instant stays exact; Paused until and a countdown end keep their seconds. F1: a registry removal that leaves an owned or detached routine without its automation entry requests a sync, and a `_deleting` set keeps the manager's own deletion out of it (a sync in that gap would have reset the routine and broken the delete). F2 counts distinct automations: one automation with two lines reads "Automation off". Brand: the light blue family of Home Assistant, a calendar with a clock in front, light and dark logos (no dark icon: it reads on both), text in Aileron Regular (CC0, the font Pillow bundles), drawn from rectangles and circles so the image data does not depend on the platform, and reproduced by `tools/make_brand.py`; the byte test skips only when the platform's PNG encoder differs, the image data test always runs. The README shows the logo through `raw.githubusercontent.com` links to `main`, so HACS renders it too. `docs/publication.md` holds the brands pull request and the HACS default submission, each step marked for the owner (O10, O11), with the points to check against the current upstream rules. The exit numbers the release 1.0.0 (`CHANGELOG.md`, `manifest.json`) and tags `v1.0.0-beta.1`; `brands` stays todo until the brands pull request merges. |
| Consequence | The Build B deploy (L70) follows the tag, now that `v0.3.0` is released and live validation A recorded. |
| PRD register entry | no |

## 2026-10-18 L73: the two load dependent test failures, found and fixed

| Field | Content |
| --- | --- |
| Context | Two tests failed once each under `pytest -n 6` and passed on reruns (L67 and the Build B exit): the manager round trip of `test_contracts.py` read `respect_manual` back differently from the summary's index, and the thirty days simulation read "Off 45 min after it turns on" at day 1 07:30 where the fan's countdown should read "Off at 7:55 AM". Both reproduced in a stress run (240 repetitions, 20 workers, 16 busy processes): 4 failures each. Traces of every write, reload, helper command and sync pass found two unrelated causes. |
| Options | For each: a fix in the integration with a regression test (rule 12), or a fix in the test. |
| Choice | The simulation found a real race in sync back, fixed in `manager.py`: `_async_sync_all` reads the file once and, after awaiting the other routines' syncs, resets every owned record its copy lacks. When several routines are written together, each reload starts or extends a sync, and a sync could read the file before the last routine's first write landed (the fan, slowest because it creates its timer first) and reach its deletion check after that routine recorded the write: the routine was reset as deleted by hand and its timer deleted, so Turn off after did nothing until the next start healed it. A record that was written after the read is now left to the sync of its own reload (the pattern of plan A4.0 item 25), proven by `test_a_sync_that_read_the_file_before_a_routines_first_write_leaves_it_alone`, which forces that interleaving. The round trip failure needs no load: it is two hypothesis examples in a row on one device that differ only in `respect_manual`. The blueprint declares that input and never reads it (L40: only the integration enforces it), and core replaces a loaded automation on a single id reload only when its name or its rendered config changed, so the entity keeps its previous blueprint inputs and the index decompiles the previous value until the next start. Nothing reads the index's `respect_manual` (the Schedule, conflicts and Today use the manager's settings), so the test is what was wrong: the round trip compares the index without that input and the manager's settings with every input, and `test_a_write_of_respect_manual_alone_keeps_the_loaded_automation` pins the core behavior. |
| Consequence | The same stress runs show no failure with the changes. The `respect_manual` half is superseded by L77: the owner chose to make the blueprint read the input instead. |
| PRD register entry | no |

## 2026-10-18 L74: the automation form folds away what Device Routines sets (O3)

| Field | Content |
| --- | --- |
| Context | The owner's look at the routine's automation form (O3, live validation A) found the inputs the integration sets (the actions, the device id, the derived flags and times, the helper references, and in schema 2 the sun flags and the late sun offset) in the two expanded sections, where a person can edit them. The owner chose to move every input the integration sets into one collapsed section. Lane 24 found that the Home Assistant frontend always shows open, without a collapse control, a section holding an input without a default (`blueprint-generic-editor.ts`, `_renderSection`), and four such inputs (`on_action`, `off_action`, `inactive_state`, `device_id`) are required on purpose. |
| Options | Which inputs count as set by the integration: all of the owner's list, or only those `decompile` never reads; for the four required ones: give them defaults (losing the core's refusal to load a routine missing them), or keep them in the always open Target section, marked. |
| Choice | The inputs a person sets in the form stay where they are, because `decompile` reads them and the form is the routine's second editor: the time flags, the kinds and the sun offsets with the times, Days, the weekly schedule, the durations, the behavior switches, the pulse, the docked guard and Only when. The eleven inputs Device Routines sets that have a default (the four sun flags, `days_end`, `crosses_midnight`, `timer_entity`, `late_window_end`, `late_sun_offset`, `override_entity`, `paused_until_entity`) move into a last section, "Set by Device Routines (do not edit)", collapsed. The four required ones stay under Target, each description starting "Set by Device Routines:", and keep no default. Layout only: the key set, defaults, value types, `REQUIRED_KEYS` and schema 2 are unchanged; `INPUT_KEYS` follows the new file order, `compile` writes it, and inputs in the earlier order read the same (the config hash sorts keys, so nothing is rewritten). A test asserts that no collapsed section holds an input without a default. |
| Consequence | Plan 6.2.1's order sentence, PRD 9.1 and TECH_SPEC 5.2 amended. The new blueprint file reaches an instance with the next deploy and start (the shipped hash upgrade of TECH_SPEC 7 step 2). |
| PRD register entry | no |

## 2026-10-18 L75: R2 done; live validation B proves S9 on a staged exact match; F4 to F6 go to lane 25

| Field | Content |
| --- | --- |
| Context | Restart R2 loaded `v1.0.0-beta.2` (`01ca0b3`) at about 21:52Z: Health `ok`, version 1.0.0, blueprint schema 2, the sandbox routine migrated with its settings unchanged. Plan 6.3 step 3 (S9) converts the sandbox device's hand written automation, but that automation also sets the device to the scheduled state when Home Assistant starts and when the device returns, which L61 counts as a partial match: it is never offered, and the golden corpus names that shape as not offered. Live validation A also reported F4 (Health reads `degraded` with `loaded_count: 0` for a few milliseconds on every routine reload), F5 (the live suite cannot open sockets under the Home Assistant test plugin) and F6 (the live Health check compares with `dev-stable`, which L58 retired). |
| Options | S9: widen the match now (a code change, a deploy and a restart before it can be seen live), or prove the conversion machinery on a staged automation that is an exact match and leave the shape to the owner. |
| Choice | S9 runs on a staged exact match on the sandbox device (two time triggers, no other trigger), named with the `stage_` prefix and removed at the end; the sandbox routine ends as plan 5.3 step 13 says. Whether a window with those catch up triggers should be offered, carrying Catch up after restart on and Respect manual changes off, is the owner's decision O18, defaulting to not offered. F4, F5 and F6 go to lane 25, harness test first. The live session that ran 5.3, already live and waiting for the 5:00 PM run, runs 6.3. |
| Consequence | O16 done. The R2 halves of S3, S4, S5 and S12 stand on their harness rows (the staged countdown ran out before the restart, phase-2 record). |
| PRD register entry | no |

## 2026-10-18 L76: live findings F4 to F6 as fixed by lane 25

| Field | Content |
| --- | --- |
| Context | Lane 25 fixed the three findings L75 routed. F4: the core reloads an automation by removing its entity, which writes the registry's restored placeholder (`unavailable`, `restored: true`) until the new entity is added; the manager counted that placeholder as not loaded, so Health read `degraded` with `loaded_count` lowered for a moment on every routine write, and for every routine at once when the blueprint install at a start reloads all automations. F5: the Home Assistant test plugin blocks sockets for every test, so the live suite never reached the instance. F6: the live Health check compared with `dev-stable`, which L58 retired as the instance's source. |
| Options | F4: hold only the manager's own writes, a time grace before `degraded`, or a hold bounded by the reload's own events. F5: a per test socket fixture, or a documented command without the plugin. F6: the deploy status (a service call, not read only) or the tags of the local clone. |
| Choice | F4: an event bounded hold: a routine's automation seen as the restored placeholder counts as loaded until `automation_reloaded` (or until the manager's own write raises), which also covers reloads other writers start; a real failed load still reads `degraded` when the reload ends (L50); a reload that aborts between removal and re adding is held until the next reload or reconcile. Ending a hold sends one `health_changed`. F5: an autouse `live_network` fixture restores the real socket functions for tests marked `live` only, proven by a subprocess pytest session that can never reach an instance; the documented command is unchanged. F6: Health's `commit` must carry a release tag (or `dev-stable`) in the local clone, and its `version` must equal that tag's version without its pre release suffix; read only. |
| Consequence | `pytest -m live` passes 4 of 4 against the instance on `01ca0b3`. The F4 fix reaches the instance with the next deploy. |
| PRD register entry | no |

## 2026-10-18 L77: the blueprint reads every input (owner's choice)

| Field | Content |
| --- | --- |
| Context | L73: the blueprint declares `respect_manual`, `on_kind` and `off_kind` and never reads them, and core replaces a loaded automation on a single id reload only when its name or its rendered config changed. A change of `respect_manual` alone therefore left the routine's automation loaded with its previous inputs, and the summary's index read the old value until the next start. `on_kind` and `off_kind` never change alone in practice (each kind flips a sun flag the blueprint reads). Nothing read the stale value. |
| Options | (a) Leave it, compare the index without `respect_manual` (L73 as committed); (b) let the blueprint read the input so the change reloads the routine; (c) let the summary take the value from the manager. |
| Choice | (b), chosen by the owner in chat on 2026-10-18. The three inputs are variables of the blueprint, read by nothing else, with a comment saying why; every input is now read (a schema test holds that), so the loaded automation always carries the inputs of the file. No input changes, so the blueprint schema stays 2 and no routine migrates; the shipped file changes, so at the next start an installed copy that was not edited is replaced (`async_ensure_blueprint`, the stored hash) and its automations reload once, and a hand edited copy raises `blueprint_modified` as before. The round trip compares the index with every input again. |
| Consequence | Changing Respect manual changes now reloads the routine's automation like any other setting, which also ends a run in progress (a pulse waiting to turn the device back on), as any other setting change already does. Ships in the same blueprint file as the form layout of L74, so the one hash upgrade at the next deploy and start carries both. Written on a branch as L74 before the form layout took that id, and renumbered when it landed. |
| PRD register entry | no |
