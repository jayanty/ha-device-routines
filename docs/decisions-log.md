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
