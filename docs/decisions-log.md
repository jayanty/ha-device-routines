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
