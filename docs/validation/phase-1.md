# Phase 1 validation record

One row per validation step of IMPLEMENTATION_PLAN Section 3, in the format of template 9.1.
Evidence is quoted as the tools print it, without instance names.

| Step | Method | Evidence | Result | Date | Approved by |
| --- | --- | --- | --- | --- | --- |
| Unit tests of the pure modules | `pytest tests/unit --cov` | Every pure module at 100 percent line and branch coverage; the DST cases are the four Stage 0 nights (2026-03-08, 2026-11-01 US; 2026-03-29, 2026-10-25 EU) and agree with `tests/stage0/test_v10_schedule_dst.py`; the state cap test renders every verb, weekday, time and format | Pass | 2026-10-17 | n/a |
| Coordinator tests | `pytest tests/integration/test_summary.py` | Discovery by entity, device, registry id, area, floor and label; read only automations ignored; debounce; own registry changes ignored; next run timer; entity time refresh; scope changes create and remove sensors; no interval or time pattern listener (AST test) | Pass | 2026-10-17 | n/a |
| Golden corpus | `pytest tests/golden` | 39 captured plus 12 synthetic automations: 56 items, 45 parsed (80 percent), every line pinned in `tests/golden/expected_lines.json` | Pass; sentence review with Jayant open | 2026-10-17 | |
| Live: devices with automations against Schedule sensors | MCP reads after the deploy and restart | Pending the restart | Open | | |
| Live: share of `source: none` | MCP reads | Pending | Open | | |
| Live: ten sentences spot checked | Jayant | Pending | Open | | |
| Live: no Repairs issues, `pytest -m live` green | MCP read, live suite | Pending | Open | | |
| C4: device page placement of a linked record's entities | Jayant looks at one device page after the restart | Pending | Open | | |
