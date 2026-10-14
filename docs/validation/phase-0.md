# Phase 0 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 1, in the format of template 9.1.
Evidence is quoted as the tools print it; the privacy check masks every match itself, so
nothing here names the instance.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| S10 first half: the pre commit hook blocks a commit containing a denylisted name | A throwaway `leak_test.md` holding one entity id from `local/denylist.txt` was staged and `git commit` was run with the installed hooks | `privacy check (staged files).....Failed`, exit code 1, four masked `denylist:` findings on `leak_test.md:1` (the entity id and the place name tokens it contains); the commit did not happen and the file was removed afterwards | Pass | 2026-10-13 | n/a (read only, local) |
| Unit tests of the privacy tooling | `pytest tests/tools --cov=tools` | 111 tests pass; coverage of `tools/` 98.9 percent | Pass | 2026-10-13 | n/a |
| Denylist built from the live registries | `python -m tools.make_denylist` over a capture of 5322 entity ids, 443 devices, 23 areas, 3 floors, 6 labels and 5 persons taken over MCP, read only | 6308 tokens written to `local/denylist.txt`; the three design documents pass the check except for the owner's byline, which decision L5 allows | Pass | 2026-10-13 | n/a (read only probes are pre approved) |
