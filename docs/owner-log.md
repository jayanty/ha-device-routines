# Owner log

Everything that waits for the owner, with the default the work takes meanwhile
(IMPLEMENTATION_PLAN Section 0.1.4, template 9.5). Nothing here stops a build; an item
marked blocking may hold a release, and only O12 is. Items are grouped into the two owner
sessions of plan Section 8.1 so they can be done in one sitting each. Answer any item in
chat by its id; a session then updates its status here.

## Owner session 1 (at restart R1, after Build A's exit)

| Id | Item | Why the owner | Default meanwhile | Needed by | Status |
| --- | --- | --- | --- | --- | --- |
| O15 | Restart Home Assistant once Build A is deployed (`v0.3.0-beta.1`), without opening Device Routines diagnostics, Repairs or options before the restart (plan 0.1.6) | Rule 1: restarts are the owner's | The instance keeps running v0.1.0; Build B starts in the harness without waiting | R1 | pending (opens at Build A exit) |
| O1 | Stage 0 cleanup C2: operate one Z-Wave, one Zigbee, one Matter and one Wi-Fi device by hand, by app and by voice, and run one script, while a session records the events (stage0-report V3) | Devices are operated by a person | Attribution ships on the time triggered V3 recording plus synthetic app and wall switch contexts (Build A lane 4); the recordings are replayed as extra fixtures when they exist | R1 session | open |
| O2 | Create a long lived access token and write `local/live.env` (`HA_URL=...`, `HA_TOKEN=...`) on the development machine, so `pytest -m live` can run (phase-1 record) | A credential, which the session never handles | The live rows use MCP reads, as Phase 1 did | R1 session | open |
| O3 | Stage 0 cleanup C3: one look at the blueprint form of the sandbox routine (sections, condition selector) and the editor's Take control button, without pressing it | A look at the UI | The harness proves validation and runtime (V5, V8); rendering is cosmetic | R1 session | open |
| O4 | Stage 0 cleanup C5: one look at the automation editor's trigger and condition pickers for the Device Routines entries with device, area and label targets | A look at the UI | The harness proves registration and the descriptions (V13); S11 exercises the trigger live | R1 session | open |

## Owner session 2 (at restart R2, after Build B's exit)

| Id | Item | Why the owner | Default meanwhile | Needed by | Status |
| --- | --- | --- | --- | --- | --- |
| O16 | Restart Home Assistant once Build B is deployed (`v1.0.0-beta.1`), after the live session has staged the restart scenario of the hour (plan 5.2) | Rule 1 | Build B's harness rows stand; the staged scenarios wait | R2 | pending (opens at Build B exit) |
| O12 | Walk through the console's Routines, Today and Settings views and say what is wrong or missing | The console is the one surface the harness cannot judge | `v1.0.0-beta.1` is released; `v1.0.0` waits for this look (blocking the final tag only) | release 1.0 | open, blocking v1.0.0 |
| O10 | Go ahead for the `home-assistant/brands` pull request, and approval of the final icon and logo | An outward facing action under the owner's account | Assets and the pull request text are prepared in the repository (plan 6.2 wave B3); nothing is opened | release 1.0 | open |
| O11 | Go ahead for the HACS default list submission | Outward facing | The submission text is prepared; nothing is opened; the custom repository install keeps working | release 1.0 | open |
| O13 | Decide the channel switch: install `v1.0.0` through HACS, turn auto deploy off, remove the package and the deploy tool (plan 6.4, R3) | The owner's instance | The instance stays on the dev channel | none | open |

## Decisions with a default already applied (answer whenever convenient)

| Id | Item | Why the owner | Default meanwhile | Needed by | Status |
| --- | --- | --- | --- | --- | --- |
| O5 | Stage 0 cleanup C6: create an AI Task entity on the local LLM endpoint so V4 can make one `generate_data` call (optional) | Instance configuration | AI summaries stay off (FR-S5 default); the AI path is tested with a fake AI Task entity | none | open |
| O6 | Merge the sibling backport jayanty/ha-device-links#59 so the `deploy-tool-parity` CI job compares the two copies (PRD D15) | The owner's other repository | The job records a skip, not a comparison | none | open |
| O7 | Try the HACS custom repository install of a release on a second instance (Phase 1 exit criterion) | Needs a second instance | Deferred indefinitely; the release zip is built and checked by CI | none | open, deferred |
| O8 | Optionally name one or two more low risk devices for live restart scenarios, so S3, S4, S5 and S12 can be staged on one restart instead of across several | Devices are the owner's | The sandbox plug alone; scenarios are staged by the clock on restarts that happen anyway (plan 5.2) and the rest stand on their harness rows | none | open |
| O9 | Decide whether to turn `input_boolean.device_routines_auto_restart` on (the 03:00 to 04:00 window, PRD D30), which would make R1 and R2 unattended | PRD D30 leaves the switch to the owner | Off; restarts are asked for in this log and the Status line | none | open |
| O14 | Veto right on the G5 decision of plan task A4.3: if the golden corpus still parses under 90 percent after the safe grammar additions, the session records a decision entry that counts the golden negatives (multi automation controllers) separately | PRD G5 is the owner's goal | The session's decision entry stands unless vetoed | none | open |

## Closed

| Id | Item | Status |
| --- | --- | --- |
| (Stage 0 C1) | Install the L16 to L18 package and confirm the last good commit follows Health | done 2026-10-18 (stage0-report) |
| (Stage 0 C4) | Device page placement of a linked record's entities | done 2026-10-17 (phase-1 record) |
| (Phase 1) | Turn off the sandbox plug's hand written automation before S2 | not an owner item since 2026-10-18: the owner asked for it in chat; the live session does it with a read before and after (plan 5.3 step 3) |
