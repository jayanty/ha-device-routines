# Phase 0 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 1, in the format of template 9.1.
Evidence is quoted as the tools print it; the privacy check masks every match itself, so
nothing here names the instance.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| S10 first half: the pre commit hook blocks a commit containing a denylisted name | A throwaway `leak_test.md` holding one entity id from `local/denylist.txt` was staged and `git commit` was run with the installed hooks | `privacy check (staged files).....Failed`, exit code 1, four masked `denylist:` findings on `leak_test.md:1` (the entity id and the place name tokens it contains); the commit did not happen and the file was removed afterwards | Pass | 2026-10-13 | n/a (read only, local) |
| Unit tests of the privacy tooling | `pytest tests/tools --cov=tools` | 111 tests pass; coverage of `tools/` 98.9 percent | Pass | 2026-10-13 | n/a |
| Denylist built from the live registries | `python -m tools.make_denylist` over a capture of 5322 entity ids, 443 devices, 23 areas, 3 floors, 6 labels and 5 persons taken over MCP, read only | 6308 tokens written to `local/denylist.txt`; the three design documents pass the check except for the owner's byline, which decision L5 allows | Pass | 2026-10-13 | n/a (read only probes are pre approved) |
| CI green on `dev` and the `dev-stable` promotion | Push of `fd3915d` to `dev`; run 38491087587 (and the watch output) | Every job succeeded: lint, typecheck, test (pinned), test (latest), hassfest, hacs, privacy, style, deploy-tool-parity, promote; `refs/tags/dev-stable` resolves to `fd3915d` | Pass | 2026-10-13 | n/a |
| HACS validation: the license check | First run on `f68eac1` failed with "The repository has no license" because GitHub detects the license on the default branch | `main` fast forwarded to the skeleton commit `2573a0d` (decision L15); GitHub reports `mit`; the HACS job passes on every later run | Pass (after L15) | 2026-10-13 | n/a |
| S10 second half: a token shaped string on a branch fails CI | Throwaway branch created through the GitHub contents API (the local hook rightly refuses such a commit), pull request jayanty/ha-device-routines#1 against `dev` | The privacy job failed in 7 seconds (docs/s10-probe.md:1: github_token: ghp***********************************AA) while lint, hassfest, hacs, style and deploy-tool-parity passed; the pull request was closed and the branch deleted | Pass | 2026-10-13 | n/a |
| Deploy tool parity | The sibling repository is private, so the job records a notice and passes without a comparison; the backport pull request jayanty/ha-device-links#59 carries the byte identical file and passes the sibling's own checks | Job output: "not readable from here; parity not checked" | Pass (not yet meaningful) | 2026-10-13 | n/a |
