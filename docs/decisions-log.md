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
