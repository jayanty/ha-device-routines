# Device Routines PRD

Oct 13, 2026 · @Jayant Yadav

Device Routines adds start and stop times, run timers and a plain language schedule summary to every Home Assistant device page, backed by real, clearly marked automations that keep running even if the integration is removed.

|  |  |
| --- | --- |
| Status | Draft v1.1 (revised 2026-10-13) for implementation by Claude Code |
| Owner | Jayant |
| Domain | `device_routines` (Decision D1) |
| Repository | `ha-device-routines`, public, MIT |
| Target platform | Home Assistant 2026.10+, distributed through HACS |
| Sibling project | `ha-device-links` (shares the deploy loop, coding standards and Stage 0 discipline) |
| Companion tabs | Technical spec (public) and Implementation plan (public) in this document; the Instance context tab stays private |

## 0. How to use this document (read first, Claude Code)

1. Read the whole document before writing code. Anything marked **ASSUMPTION** is unverified and has a Stage 0 item that closes it.
2. Do **Stage 0** (Section 13) before any Phase 1 code. Read only probes are pre approved. Every write probe needs Jayant's explicit approval for that specific item, a read before it and a read after it proving the state was restored.

   Note: since 2026-10-17 write probes and live write scenarios are pre approved, and the read before and after each write stays (decision L26, `docs/decisions-log.md`).

3. Produce `docs/stage0-report.md` that closes or amends every ASSUMPTION and records anonymized fixtures under `tests/fixtures/`.
4. Section 14 is the decision register. Each decision has a default. If Jayant has not answered, proceed with the default and record that in the Stage 0 report.
5. This document has two tabs. **This tab is public** and becomes `docs/PRD.md` in the repository. The **Instance context** tab is private: it becomes `CLAUDE.local.md` (gitignored) and must never be committed, quoted in issues, or copied into fixtures, tests, docs or commit messages (Section 3, P1).
6. Never restart Home Assistant. Restarts are Jayant's to perform (Section 11).
7. Style rule for all generated docs, UI strings and commit messages: never use the em dash character.

**Added in v1.1.** This document now has four tabs. The Technical spec tab Technical spec (public) turns this PRD into module, blueprint, storage, pipeline and test specifications, and the Implementation plan tab Implementation plan (public) is the build order Claude Code follows, phase by phase, with validation steps and a handoff section. Where they disagree, the PRD defines behavior, the spec defines how, and the plan defines when. Two more rules: (8) Phase 0 of the plan (repository, CI, privacy tooling, deploy pipeline) runs before Stage 0; (9) every entity, action, trigger, condition and WebSocket command goes through the single service layer (P16).

Private instance context for `CLAUDE.local.md`: Instance context (private)

## 1. Summary

Home Assistant makes the most common device behaviors the hardest to set up. "Run the air purifier from 5 PM to 9 AM", "turn the fan off after 60 minutes", "start the vacuum at 9:45 on weekdays" each need a hand written automation, written in a different place from the device, with no way to see from the device itself what is scheduled to happen to it.

Device Routines fixes both halves:

- **Configure on the device page.** A device opted in to routines gets a small set of native controls in its Configuration card: Turn on at, Turn off at, Days, Turn off after, Turn back on after. Nothing to learn: they are HA's own time pickers, number fields and toggles.
- **See everything on the device page.** Every device that any automation acts on gets a **Schedule** sensor whose state reads like a sentence ("Off at 9:00 AM") and whose attributes list each routine and automation that controls the device, with its next run.

Under the hood, each device's routine is a normal Home Assistant automation built from a blueprint the integration ships. The integration writes and maintains it; Home Assistant runs it. Traces, the automation list, the device page Automations card and git tracking of `automations.yaml` all work unchanged, and the routine keeps working if the integration is disabled.

### 1.1 What exists today and why build

| Option | What it does well | Gap for this use case |
| --- | --- | --- |
| Hand written automations | Unlimited flexibility | One per device, written away from the device, no summary, easy to get restart behavior wrong |
| Scheduler component plus scheduler card (HACS) | Mature time scheduling with conditions | Lives on dashboard cards, own storage instead of automations, no run timers, blind to existing automations |
| Auto Off Timer, Simple Timer (HACS) | Turn off after a timeout | Duration only; no schedules, no summary |
| A shared blueprint, used by hand | Native, git tracked, shows on the device page Automations card | User still builds each instance in the automation editor; no summary; no two way sync |

None of them configure on the device page or explain what already controls a device. Device Routines does both, and deliberately reuses the blueprint approach as its execution layer rather than inventing a scheduler.

## 2. Goals, non goals, success measures

The bar is that someone who has never heard of the integration can set a routine and read a device's schedule without instructions.

### 2.1 Goals

| # | Goal | Measure |
| --- | --- | --- |
| G1 | Set a daily on/off routine for a device in under 60 seconds from its device page, with no YAML and no automation editor | Timed walkthrough on a fresh device |
| G2 | Anyone can tell what will happen to a device next by glancing at its device page | The Schedule sensor state is a sentence of 40 characters or less naming the next action and time |
| G3 | Managed automations are impossible to confuse with hand written ones | Every managed automation carries all markers in Section 8; the automation list can isolate them in one click; a test proves the integration never writes to an unmarked automation |
| G4 | Routines survive restarts and reconnects | A transition missed while HA was down is applied within 60 seconds of startup; a running Turn off after countdown resumes with the correct remaining time after a restart |
| G5 | Summaries are trustworthy | At least 90% of automations in the golden corpus are summarized by the deterministic parser; zero wrong deterministic summaries; anything the parser cannot read is labeled as such, never guessed |
| G6 | Engineering bar matches Device Links | mypy strict with zero errors, 95%+ coverage, hassfest and HACS validation in CI, every quality scale rule accounted for in `quality_scale.yaml` |
| G7 | No instance data ever reaches the public repository | The privacy check (Section 11.3) passes on every commit and in CI |
| G8 | Zero upkeep after setup | A simulated 30 day harness run with device renames, an integration upgrade, a config restore from git, a device removed and a device offline raises no Repairs issue outside the three documented cases (edited blueprint file, invalid form edit, missing weekly blocks) and needs no other human action |
| G9 | Console ready | Every capability reachable from a device page is reachable through the WebSocket API with identical semantics; contract tests prove it |

### 2.2 Non goals (v1)

- Not a general automation engine and not a replacement for the automation editor. Anything beyond the routine catalog stays a normal automation, which the Schedule sensor still summarizes.
- No climate setpoint scheduling, media playback scheduling or scenes in v1. Climate gets on/off only.
- No scheduled actions that weaken security: never unlock, never open a garage door or gate, never disarm an alarm (Section 5.4). These are refused in code, not just hidden.
- No entities without a device. Routines live on device pages; device less entities are out of scope for v1.
- No cloud, no telemetry, no outbound calls. The optional AI summary goes only to an AI Task entity the user explicitly selects.
- No sub minute precision: times are minutes; durations are minutes or hours. No house wide pause or vacation mode in v1 (D24, Section 5.7).

## 3. Design principles and hard constraints

These are constraints, not preferences. A design that breaks one needs a decision register entry before it ships.

| # | Principle | What it means in practice |
| --- | --- | --- |
| P1 | **Public repo, zero instance data** | The repository is public from the first commit. It never contains entity ids, device ids, device or area names, IPs, hostnames, tokens, URLs or automation text from any real home. Instance context lives only in gitignored `CLAUDE.local.md` and `local/`. Fixtures are anonymized by a tool. A privacy check blocks commits (Section 11.3). |
| P2 | **Built for HACS from day one** | One integration per repo under `custom_components/device_routines/`, `hacs.json`, brand assets, GitHub releases with a zip, hassfest and HACS actions in CI. Nothing assumes the author's setup. |
| P3 | **Git is the source; HA pulls** | Code reaches Home Assistant only by Home Assistant pulling it from GitHub: HACS releases for stable versions, and the deploy tool for development builds (Section 11). Nothing is copied from a laptop. |
| P4 | **No training required** | Native HA controls, plain words, sensible defaults, and only the options that make sense for the device. Advanced options exist but stay out of sight until needed. The Schedule sentence confirms every setting the moment it is made. |
| P5 | **Managed automations are unmistakable** | Every automation the integration creates carries a blueprint, an id prefix, an alias prefix, a category, a label, an icon and a description banner. The integration only ever touches automations that carry its authoritative markers (Section 8). |
| P6 | **Home Assistant runs it; the integration configures it** | Routines execute as standard automations, timers and helpers. The integration is not in the runtime path: if it is disabled, existing routines keep working; only editing and summaries stop. |
| P7 | **Never touch what it did not create** | Hand written automations are read for summaries and never modified. Conversion of a hand written automation into a routine is always an explicit user action, and the original is disabled, never deleted. |
| P8 | **One source of truth** | A routine's settings live in its automation's blueprint inputs, inside `automations.yaml`. Device page controls read and write those inputs. No second copy that can drift, and git sees every change as a normal diff. |
| P9 | **Native constructs over templates** | Time, state and trigger conditions over Jinja; timer helpers over `for:` clauses; purpose specific triggers where they exist. Templates only where no native construct can express the logic, each one unit tested. |
| P10 | **Restart and reconnect safe** | No routine depends on a `for:` clock that resets on restart. Missed transitions are caught up; countdowns resume. |
| P11 | **Safety by refusal** | Actions that weaken physical security are not schedulable at all (Section 5.4). |
| P12 | **Local first** | No cloud and no outbound calls. The optional AI summary uses only an AI Task entity the user chooses, and says so before it is enabled. |
| P13 | **Stability over novelty** | The minimum HA version is the one Stage 0 validated, and later never more than one minor behind current (D14); no reliance on Labs or beta features; internals are reached through one version guarded adapter module. |
| P14 | **Verify before write** | Every write path is proven read only first in Stage 0, then with an approved write probe, before production code depends on it. |
| P15 | Zero onboarding, zero upkeep | Install is one click with no fields. Every recoverable situation self heals (Section 3.1). Repairs issues are raised only when a human decision is genuinely required, and each has a one click fix. No notifications, no logs to read, no periodic chores |
| P16 | One service layer | Device page entities, actions, triggers, conditions and the WebSocket API all call the same RoutineManager and SummaryCoordinator methods. Nothing lives only in a platform, so the future console (Section 4.5) is a thin client with no new semantics |

### 3.1 Zero maintenance guarantees

After the one click setup the integration never asks for routine upkeep. Everything below happens on its own, is visible in diagnostics and the Health sensor, and raises a Repairs issue only where the last column says so. The Implementation plan tests every row in the harness (G8).

| Situation | Automatic response | Human action |
| --- | --- | --- |
| Integration installed | The config flow completes with no fields; Schedule sensors appear on every device an automation acts on (scope setting); the label, category and blueprint are created | None |
| Device renamed | The alias, helper names and the Schedule sentence follow the new name while the alias still matches the generated pattern | None |
| Target entity id renamed | The blueprint input is rewritten to the new id and the automation reloaded | None |
| Device removed from Home Assistant | The routine is turned off; after the cleanup period (Section 10.4, default 30 days) the automation and its helpers are deleted | None |
| Device opted out (label removed) | Controls removed, routine turned off, settings kept; cleanup after the period | None |
| Timer or schedule helper missing | Recreated with the same entity id | Weekly blocks re entered once (one Repairs issue) |
| Blueprint file missing | Reinstalled from the shipped copy; automations reloaded | None |
| Blueprint file edited by hand | Left untouched; routines keep running on the edited copy | One click Restore the shipped blueprint in Repairs |
| Integration updated with a new blueprint schema | Blueprint replaced, owned automations migrated, Store migrated; previous inputs kept for a one click restore | A restart, as for any custom integration update |
| Home Assistant updated | The adapter version guard runs at startup; if an internal changed, editing is disabled and one Repairs issue raised while routines keep running | Update the integration when a fix ships |
| automations.yaml restored from git | The ownership index is rebuilt from the markers; entities follow the restored inputs | None |
| Owned automation fails to load | Regenerated once from the last valid inputs; if it still fails, routine off and one Repairs issue with restore | Only if regeneration fails |
| Managed automation edited into an invalid state | Routine off, nothing overwritten | One click Restore last valid settings |
| Managed automation deleted by hand | Settings reset; the device stays opted in | None |
| Restart or device offline | Catch up applies the expected state; countdowns resume with their remaining time | None |
| Pause ends | The routine resumes with catch up (D20) | None |

## 4. User experience

The device page is the whole product for most users: a handful of controls in the Configuration card and one Schedule sentence, all native HA components.

### 4.1 Opting a device in

Nothing is required at install. The config flow has no fields; it ends with one optional screen that lists devices already driven by time based automations and offers to give them routine controls (all unchecked, skippable, available again later in options). Routine controls then come from any of three equivalent paths, kept in sync:

1. **Label.** Add the `Routines` label on a device page. The integration creates this label (icon `mdi:calendar-clock`) on setup. It is the visible truth: every other path applies the label, and removing it opts the device out.
2. **Options.** A native device picker, "Devices with routines", plus the same suggestions screen.
3. **Console and API** (Section 4.5, Phase 4) for bulk changes.

Opting out removes the device's routine controls and turns its routine automation off without deleting it; opting back in restores the previous settings. Cleanup is automatic (D28): a managed automation whose device has been opted out, or removed from Home Assistant, for longer than the cleanup period (Section 10.4, default 30 days) is deleted together with its helpers. The hub keeps a Clean up now button for people who do not want to wait; nothing requires pressing it.

### 4.2 What appears on the device page

All entities use `has_entity_name`, translation keys and icons. Labels adapt to the device's domain (Section 5.3), so a vacuum shows "Start at" and a cover shows "Open at".

| Entity | Platform | Category | Shown by default | Behavior |
| --- | --- | --- | --- | --- |
| Schedule | `sensor` | none (Sensors card) | Yes, on every device any automation acts on | State: the next action as a sentence ("Off at 9:00 AM"). Attributes: one entry per routine and automation (Section 6). |
| Routine | `switch` | config | Yes | Mirrors the managed automation's on/off state both ways. Off means nothing runs: this is the indefinite disable (FR-R14). |
| Turn on at | `time` | config | Yes | Empty until set. Setting it creates the routine if none exists. |
| Turn off at | `time` | config | Yes | As above. Either time alone is valid. |
| Days | `select` | config | Yes | Every day, Weekdays, Weekends, Some days (the same times on a day set chosen in the routine form or the console, D34), Weekly schedule. Weekly schedule creates and links a native `schedule` helper (FR-R2) and greys out the two time entities. |
| Turn off after | `number` (minutes, box mode) | config | Yes, for domains that support it | 0 means off. Applies to turn ons not caused by the schedule (Section 5.2). Cannot be set together with Turn back on after (D27). |
| Turn back on after | `number` (minutes) | config | No (advanced) | 0 means off. Keep alive behavior. Cannot be set together with Turn off after (D27). |
| Catch up after restart | `switch` | config | No (advanced) | Default on. |
| Respect manual changes | `switch` | config | No (advanced) | Default on. |
| Skip next | `button` | none (Controls card) | Yes | Skips the next action the Schedule sentence shows (FR-R11). Unavailable when nothing is scheduled. |
| Paused until | `datetime` | none (Controls card) | Yes | Empty unless paused. Setting a future time pauses the routine (FR-R12). |
| Resume | `button` | none (Controls card) | Yes, unavailable unless paused or skipping | Ends a pause or skip now (FR-R13). |
| Manual override | `switch` | diagnostic | Only while active | On when a manual change (Section 9.3) left the device in a state the schedule did not ask for; cleared by the next scheduled change. Turning it off resumes the schedule immediately. Its last\_change\_source attribute names what changed the device last. |
| Routine controls | `select` | config | Only when the device has more than one controllable entity | Picks which entity the routine drives (Section 5.3). |

Advanced entities are created disabled by default, so HA's own "entities not shown" control on the device page is the disclosure mechanism. No custom UI is needed to keep the page short.

### 4.3 Feedback without training

- The Schedule sentence updates within one second of any change, so the user sees in words what they just configured.
- Invalid combinations are prevented at the control, not reported later: a Turn on at equal to Turn off at is rejected with a translated message; Turn back on after is unavailable while a schedule says off.
- Problems become Repairs issues with one click fixes (Section 9.4), never log lines the user has to find.
- The managed automation is reachable from the device page's existing Automations card, and opening it shows the blueprint form with the same settings in the same words.

### 4.4 Hub device

One service device, "Device Routines", holds the house wide items:

- **Routines** (`sensor`): the count of active routines. Its attributes list every managed routine with `device`, `area`, `summary`, `next_action`, `status` (active, paused, skipping, off, detached, missing target) and `automation`, so a markdown or auto entities card shows all managed automations in one place before the console exists.
- **Problem** (`binary_sensor`, device class problem): on while any Repairs issue from this integration is open; the attributes list the issue ids.
- **Health** (`sensor`, diagnostic): `ok`, `degraded` or `error`, with the attributes `version`, `commit`, `branch`, `deployed_at`, `channel` (dev or hacs), `blueprint_schema`, `blueprint_status`, `owned_count`, `loaded_count`, `issues` and `ha_version`, read from the deploy tool's `.deployed` file and the manifest (Section 11.2).
- **Clean up now** (`button`, config): runs the automatic cleanup immediately.

There is no house wide pause in v1 (D24). The action and WebSocket schemas accept a target of `all` so one can be added later without a breaking change.

### 4.5 Management console (Phase 4) and the views available today

Two native views already show every managed automation in one place with no code: the automation list filtered by the `Routines` label or the `Device Routines` category, and the label page for `Routines`, which also lists the helpers. The hub Routines sensor (Section 4.4) adds next actions and status for dashboards.

The console is a sidebar panel, admin only, built in Phase 4 on the WebSocket API of Section 7.5 (D31). It introduces no semantics of its own: every control calls the same service layer as the device page (P16).

| View | Shows | Can do |
| --- | --- | --- |
| Routines | A table of every managed routine: device, area, Schedule sentence, status, next action, pause state; detached routines and conversion candidates in their own sections | Skip next, pause until, resume, enable and disable per row or for a selection; open the device page or the automation; opt devices in or out; edit settings inline |
| Today | A timeline of every scheduled action in the house by time, grouped by area, combining routines and summarized automations, with conflicts highlighted | Jump to a device page |
| Settings | Every global setting of Section 10.4, the maintenance actions (rebuild index, reinstall blueprint, clean up now, refresh summaries) and Health | Edit settings; run maintenance actions |

A calendar view of routine actions (Section 5.7) remains a candidate complement.

## 5. Routine catalog

Six options cover the routines people actually write by hand; everything else stays a normal automation. Priorities: **P0** ships in Phase 2 (first routine release), **P1** high value follow up, **P2** later.

### 5.1 Options

**FR-R1 (P0) Scheduled times.** Turn on at and Turn off at, either or both, on the selected Days. Windows that cross midnight (on 17:00, off 09:00) are handled natively. AC: a 17:00 to 09:00 window turns the device on at 17:00 and off at 09:00 the next day, and the Schedule sensor reads "On at 5:00 PM" during the off period.

**FR-R2 (P1) Custom weekly schedule.** Days = Weekly schedule creates a native `schedule` helper named "\<device name> routine", labels it `Routines`, and the routine follows its blocks (block start = on, block end = off). The user edits it in HA's own weekly editor. Adjacent blocks across midnight must not cause an off/on blip (ASSUMPTION A6). AC: a schedule with different times on weekdays and weekends drives the device correctly for a simulated week.

**FR-R3 (P0) Turn off after.** After any turn on (by hand, app, voice, another automation), turn off after N minutes. Turning the device off cancels the countdown; turning it on again restarts it. The countdown survives restarts (Section 9.2). Turn off after and Turn back on after are mutually exclusive on one routine (D27). AC: on at 10:00, HA restarted at 10:20, device turns off at 10:30.

**FR-R4 (P1) Turn back on after.** After any turn off not caused by this routine, turn the device back on after N minutes. Never fires while the schedule says off or while routines are paused. AC: a device that turns itself off at 14:00 is back on at 14:00 plus N.

**FR-R5 (P0) Catch up after restart.** On HA start, and when the device returns from unavailable for 10 seconds, set the device to the state the schedule expects now, unless a manual override is active. AC: HA down from 16:55 to 17:10 with a 17:00 on time; device is on by 17:11.

**FR-R6 (P0) Respect manual changes.** A change not made by an automation sets Manual override, which suppresses catch up and keep alive until the next scheduled time. The next scheduled time always runs and clears the override. AC: device turned on by hand at noon inside an off window, HA restarted at 12:30, device stays on; at 17:00 the routine takes over.

**FR-R7 (removed).** No house wide pause in v1 (D24). Device pauses use FR-R12; room level pauses use the actions with an area or label target; vacation handling is deferred to the future calendar view in Section 5.7.

**FR-R8 (P1) Pulse.** At a time, switch to the opposite state for N minutes, then restore, only if the device has been in its current state for at least 5 minutes. Exposed in the blueprint form only (advanced, no device page control). AC: fan on since 06:00; at 08:00 it is off for 3 minutes, then on.

**FR-R9 (P2) Only when.** One or more native HA conditions gating scheduled actions, edited with the blueprint's `condition` selector. Covers guards like "only if docked and battery above 95%" and "skip when guest mode is on".

**FR-R10 (P2) Sun relative times.** Turn on at and Turn off at accept sunrise or sunset plus or minus an offset, through a companion select (Time, Sunrise, Sunset) and an offset number.

### 5.2 How options interact

The rules below are implemented once, in the blueprint, and covered by the behavior test matrix (Section 12).

| Situation | Rule |
| --- | --- |
| Routine paused (its Paused until is in the future) | No scheduled action runs and no countdown fires; running countdowns pause and resume with their remaining time; each skipped action fires `device_routines_action_skipped` |
| Skip next pressed | Paused until is set to one minute after the next shown action; a window start skips its paired end too; a running countdown is cancelled |
| A pause or skip ends (by time or Resume) | Catch up applies if it is on (D20): inside a window the device is set to the window's state |
| Device changed by hand while paused | Allowed; Manual override is not set |
| Routine switch off | Nothing runs; a Paused until value is kept and applies again only if the routine is turned back on before it ends |
| A scheduled time arrives | It always runs (unless paused) and clears Manual override |
| Device changed by hand between scheduled times | Respect manual changes on: Manual override on, catch up and keep alive suppressed. Off: nothing special happens |
| Turn off after and a scheduled on window | Turn off after does not apply inside a window that has an explicit Turn off at; it does apply after a Turn on at that has no Turn off at ("on at 7:00 for 30 minutes") |
| Turn back on after and a manual off | Keep alive wins over Respect manual changes, by design: its purpose is to undo offs. To stop it, turn the Routine off or pause it |
| Turn back on after and the schedule | Never fires during a scheduled off period. It cannot be set together with Turn off after (D27), so the two durations never interact |
| Days | Limits scheduled times only; durations apply every day |
| Daylight saving changes | Times are local wall clock. Behavior for a time that is skipped or repeated follows HA's time trigger (ASSUMPTION A7) and is documented |

### 5.3 Supported domains

The integration picks the device's controllable entity: the single entity in a supported domain with no entity category. If there are several, the Routine controls select appears and defaults to the first by entity registry order.

| Domain | On action, label | Off action, label | Options | Built in guard |
| --- | --- | --- | --- | --- |
| `switch`, `light`, `fan`, `input_boolean`, `humidifier` | turn on, "Turn on at" | turn off, "Turn off at" | All | None |
| `climate` | turn on, "Turn on at" | turn off, "Turn off at" | Times, Days, Turn off after | None |
| `media_player` | none | turn off, "Turn off at" | Turn off at, Days, Turn off after | None |
| `vacuum`, `lawn_mower` | start, "Start at" | return to dock, "Return to dock at" | Times, Days | Start only when docked (on by default) |
| `cover` | open, "Open at" | close, "Close at" | Times, Days, Close after | Open refused for garage, gate and door device classes |
| `lock` | none | lock, "Lock at" | Lock at, Days, Lock after | Unlock refused |
| `valve` | open, "Open at" | close, "Close at" | Times, Days, Close after | Open refused for gas device class |

### 5.4 Refused actions

The integration never schedules, delays or re-triggers an action that weakens physical safety or security: unlocking a lock, opening a garage door, gate or door cover, opening a gas valve, or disarming an alarm panel. Alarm panels and sirens are not supported domains at all. The refusal lives in the pure compiler (Section 7) and is enforced again when blueprint inputs are synced back from the automation editor, so a hand edit to the blueprint form cannot introduce one. Safety positive variants (Lock at, Lock after, Close after) are supported.

### 5.5 Skip, pause and disable

Every "not now" case is one stored value per device, **Paused until**, so the blueprint checks a single rule and a restart cannot lose the state.

| Control | On the device page (Controls card) | Action | Effect |
| --- | --- | --- | --- |
| Skip next | `button` "Skip next" | `device_routines.skip_next` | Skips the action the Schedule sentence shows next (D18, D19) |
| Pause until | `datetime` "Paused until" | `device_routines.pause` with `until` or `for` | No scheduled action runs and no countdown fires until then |
| Resume | `button` "Resume", available only while paused or skipping | `device_routines.resume` | Ends the pause now; catch up per D20 |
| Disable | The existing `switch` "Routine" turned off | `device_routines.disable`, `device_routines.enable` | Nothing runs until turned back on |

**FR-R11 (P0) Skip next.** Sets Paused until to one minute after the action it skips. The skipped action is the one the Schedule sentence shows next: a window start (its paired end is skipped too, so the whole occurrence is skipped), a one shot run, or a running countdown (cancelled; the device stays as it is). Pressing again extends the skip to the following action. Unavailable when nothing is scheduled. AC: at 15:00 with a 17:00 to 09:00 window, Skip next leaves the device off tonight and the sentence reads "Skipped, on Thu 5:00 PM".

**FR-R12 (P0) Pause until.** A future value pauses; a past value is rejected with a translated message. The action takes exactly one of `until` (datetime) or `for` (duration). While paused, no scheduled action runs, no countdown starts, and running countdowns pause and later resume with their remaining time. Manual changes still work and do not set Manual override. The sentence reads "Paused until Sun 6:00 PM".

**FR-R13 (P0) Resume.** Ends a pause or skip immediately, then applies catch up if it is on (D20).

**FR-R14 (P0) Disable and enable.** Map to the Routine switch, which already turns the managed automation off and on (Section 8.2). The sentence reads "Routine off".

**FR-R15 (P0) Actions.** All four take a native target (device, area, label or entity), filtered to devices with routines. Targets without a routine are ignored and listed in the response; no matching target raises `ServiceValidationError`. Optional response per device: `{device, skipped_action | paused_until, next_action}`. Names, descriptions and fields are translated in `services.yaml` and `strings.json`.

**FR-R16 (removed).** No hub level pause in v1 (D24).

Scope: routines only (D22). Skip and pause never touch hand written automations; their Schedule lines are unaffected. The new controls carry no entity category, so tile cards and voice reach them; voice exposure follows HA's own exposure defaults and is never forced on.

### 5.6 Triggers and conditions

**FR-R17 (P1).** Other automations can react to routine state through the automation editor's own trigger and condition pickers, in HA's purpose specific shape (`trigger: device_routines.paused` with `target` and `options`).

| Kind | Key | Fires or is true when |
| --- | --- | --- |
| Trigger | `device_routines.action_skipped` | A scheduled action or countdown did not run because the routine was skipped or paused |
| Trigger | `device_routines.paused` | A routine becomes paused or skipping, from any source |
| Trigger | `device_routines.resumed` | A pause or skip ends, by time or by Resume |
| Condition | `device_routines.is_paused` | The routine is paused or skipping |
| Condition | `device_routines.is_active` | The routine is on and not paused |

All take a device, area or label target. Triggers support `behavior: each | first | all`, conditions `any | all`, matching HA's conventions. Underneath, the blueprint fires a bus event, `device_routines_action_skipped`, at the moment it skips, so the skip appears in traces and is usable as a plain event trigger even if the integration is disabled. The trigger and condition platforms depend on HA's integration platform API for purpose specific triggers and conditions (ASSUMPTION A14).

### 5.7 Future, not scheduled: calendar view

A `calendar.device_routines` entity could list every upcoming routine action for the next 14 days in HA's Calendar panel and calendar cards. Deleting an occurrence would mean Skip; creating an event named Pause over a device would mean Pause until. It needs its own design before it enters a phase: how an event names its device, how recurring routine actions map to calendar recurrence, and how calendar edits and Paused until stay consistent. A read only version could replace or complement the Today panel (Section 4.5). Vacation handling, a house wide pause with dates, is designed here too (D24).

## 6. Schedule summary

The Schedule sensor ships first (Phase 1) because it is read only, useful on day one, and explains devices whether or not they use routines.

**FR-S1 (P0) Discovery.** For every device, find each automation whose actions target one of the device's entities, directly or through the device, its area or a label. Use HA's reference helpers so YAML defined automations are included (ASSUMPTION A3), and read each automation's configuration from the loaded automation entity rather than the config REST endpoint, which cannot see YAML automations (ASSUMPTION A4). Automations that only read the device (in a trigger or condition) are ignored.

**FR-S2 (P0) Deterministic parser.** A pure module (no HA imports) turns an automation config into one line per action on this device. It understands:

| Part | Understood |
| --- | --- |
| Triggers | `time` (fixed, helper or timestamp sensor), `time_pattern`, `sun`, `state` and `numeric_state` with `for`, `homeassistant` start, `calendar`, purpose specific `schedule.*`, `timer.*`, `vacuum.*` and device state triggers |
| Conditions | `time` (weekday, after, before), `state`, `numeric_state`, `sun`, `trigger`, `and`, `or`, `not`, purpose specific `*.is_*` |
| Actions | turn on, turn off, toggle, start, return to base, open, close, lock; `delay` sequences; `choose` and `if` branches keyed by trigger id |

Output examples: "Weekdays 9:45 AM: start (if 7 conditions pass)", "8:00 AM: off for 3 min, then on", "Off 60 min after it turns on". Anything the parser cannot read (templates, `repeat`, scripts, events) is never guessed: the line ends with "plus custom logic" or, if nothing was understood, reads "Automation: \<alias> (custom logic)".

**FR-S3 (P0) Next run.** Computed for timed lines from triggers plus weekday and time conditions, and from `sun.sun` for sun triggers. Event driven lines have no next run and read as "When ...".

**FR-S4 (P0) Sensor state and attributes.** State is the earliest next timed action, 40 characters or less: "Off at 9:00 AM" today, "Start Wed 9:45 AM" on another day. With no timed action it shows the first event driven line; with nothing at all the sensor is not created. Attributes:

```yaml
items:
  - kind: routine | automation | detached_routine
    automation: automation.<id>
    alias: <alias>
    summary: <line>
    next_run: <ISO datetime> | null
    source: parser | ai | none
    enabled: true | false
paused_until: <ISO datetime> | null
skipped_action: <line> | null
conflicts: [<item index pairs with a reason>]
```

Routines always sort first, so a device page shows "Routine" lines above "Automation" lines.

While a routine is paused or skipping, the state says so first and then names the next action that will actually run: "Skipped, on Thu 5:00 PM", "Paused until Sun 6:00 PM", "Routine off". Lines for hand written automations are never changed by a routine pause.

Times in every sentence follow the Time format setting (Section 10.4, D32): 12 hour or 24 hour, resolved automatically from the Home Assistant country unless overridden. Sentences are built from translation tables so other languages can be added without code changes.

**FR-S5 (P1) Optional AI summary.** If the user selects an AI Task entity in options, lines the parser cannot fully read are sent to it, one automation at a time, as the trigger, condition and action blocks only (entity ids, no states or attributes), with a fixed prompt asking for 12 words or less. Results are cached by config hash and regenerated only when the automation changes. AI lines are marked `source: ai` and shown with an "(AI)" suffix. The options flow says exactly what is sent and where. Off by default; at most 20 calls per hour; never during startup.

**FR-S6 (P1) Conflicts.** Flag pairs that drive the same entity in opposite directions in the same minute, and automation actions that contradict a routine window. Shown in `conflicts` and in the Today panel. A Repairs issue is raised only for a routine against another automation at the same minute.

**FR-S7 (P0) Freshness without polling.** Recompute on automation reload, automation entity add or remove, entity and device registry changes, and at each item's next run. Debounce 2 seconds.

**FR-S8 (P0) Scope option.** Options: show Schedule on all devices with automations (default), only on devices with routines, or nowhere.

## 7. Architecture

The integration is a compiler and a reader. It compiles device page settings into blueprint inputs on one managed automation per device, and it reads every automation to write the Schedule sentence. Home Assistant's own automation engine, timer helpers and schedule helpers do all the running.

&#91;embedded content: architecture · device page, integration, Home Assistant core\]

Settings flow from the device page into blueprint inputs and edits flow back; only the highlighted path runs the device, and it needs nothing from the integration.

### 7.1 Components

| Component | Pure (no HA imports) | Responsibility |
| --- | --- | --- |
| `domains.py` | Yes | Domain profiles: actions, labels, supported options, built in guards, refused actions |
| `compiler.py` | Yes | Routine settings plus domain profile to blueprint inputs; validation; refusals (Section 5.4) |
| `markers.py` | Yes | Builds and checks the ownership markers and config hash (Section 8) |
| `parser.py`, `nextrun.py`, `conflicts.py` | Yes | Summary lines, next run times, skip targets, conflict detection (Sections 5.5 and 6) |
| `blueprints/device_routine.yaml` | n/a | The single blueprint every routine uses; owns all runtime behavior in Section 5.2 |
| `manager.py` | No | RoutineManager: debounces entity writes, calls the compiler, writes automations, syncs blueprint edits back to entities, maintains the ownership index |
| `ha_adapter.py` | No | The only module that touches HA internals: writing automation config, installing the blueprint, creating timer and schedule helpers, reading automation configs and references. Version guarded; fails fast into a Repairs issue (Decision D2) |
| `summary.py` | No | Discovery, parser orchestration, optional AI Task calls, Schedule sensors |
| `services.py` | No | `skip_next`, `pause`, `resume`, `disable`, `enable` with native targets (FR-R15) |
| `trigger.py`, `condition.py` | No | Purpose specific triggers and conditions (FR-R17) |
| Platforms | No | `sensor`, `switch`, `time`, `datetime`, `select`, `number`, `binary_sensor`, `button` |
| attribution.py | No | Manual change attributor: a bounded map of automation and script run contexts; classifies target state changes as automation, user or device; drives the Manual override switch (Section 9.3) |
| settings.py, sentence.py | Yes | GlobalSettings dataclass with defaults, validation and option migration (Section 10.4); sentence building with the time format and the 40 character cap |
| websocket\_api.py | No | The console contract (Section 7.5): list, get, set, action, opt, today, settings and maintenance commands plus a subscription; thin wrappers over the service layer |
| migration.py, maintenance.py, health.py | No | Config entry, Store and blueprint input schema migrations with owned automation rewrites; the maintenance actions; the hub Health sensor source reading .deployed and the manifest plus the startup self checks |

### 7.2 Write path: a setting changes

1. The user sets Turn off at on the device page. The `time` entity hands the value to RoutineManager and shows it immediately.
2. After a 1 second debounce (so changing several settings produces one write), the compiler validates the full settings and produces blueprint inputs, or a translated error that reverts the entity.
3. `ha_adapter` writes the automation entry (create or update) through HA's automation config write path (ASSUMPTION A2), then reloads only that automation.
4. The new config hash is recorded in the ownership index. The Schedule sensor recomputes. Total time under 2 seconds.

### 7.3 Sync back: the blueprint form is edited directly

1. Someone opens the managed automation and changes an input in the blueprint form.
2. On the automation reload event, RoutineManager sees a config hash it did not write, parses the inputs, and runs the compiler's validation, including refusals.
3. Valid: entities update to match. The device page and the automation editor never disagree.
4. Invalid (for example a refused action): the routine is turned off, nothing is overwritten, and a Repairs issue offers "Restore last valid settings".

This is why the system has no drift concept for settings: the blueprint inputs are the only copy, and both editors read and write them.

### 7.4 Package layout

```text
custom_components/device_routines/
  __init__.py          setup, unload, services, blueprint install check
  manifest.json        dependencies: automation, blueprint, timer, schedule; after_dependencies: ai_task
  config_flow.py       single instance, zero field setup, optional suggestions, options, removal setting
  const.py
  models.py            dataclasses: RoutineSettings, DomainProfile, SummaryItem, Marker (pure)
  domains.py           (pure)
  compiler.py          (pure)
  markers.py           (pure)
  parser.py, parser_grammar.py   (pure)
  nextrun.py           (pure)
  conflicts.py         (pure)
  sentence.py          (pure)
  settings.py          (pure) GlobalSettings
  manager.py           RoutineManager, the service layer
  attribution.py       manual change attributor (Section 9.3)
  ha_adapter.py        the only module that reaches HA internals
  summary.py           SummaryCoordinator
  maintenance.py       maintenance actions
  health.py            hub Health sensor source
  migration.py         config entry, Store and blueprint schema migrations
  websocket_api.py     console contract (Section 7.5)
  entity.py, sensor.py, switch.py, time.py, select.py, number.py, binary_sensor.py, button.py, datetime.py, services.py, trigger.py, condition.py
  blueprints/device_routine.yaml
  diagnostics.py, repairs.py
  strings.json, translations/en.json, icons.json, quality_scale.yaml, services.yaml
  frontend/            Phase 4 console bundle
tools/                 ha_deploy.py, anonymize.py, make_denylist.py, privacy_check.py, style_check.py, ha_package/
tests/                 unit, golden, blueprint, integration, tools, live (read only), fixtures (anonymized only)
docs/                  PRD.md, TECH_SPEC.md, IMPLEMENTATION_PLAN.md, stage0-report.md, decisions-log.md, user-guide.md, api.md
hacs.json, README.md, CHANGELOG.md, LICENSE, CLAUDE.md, brand/, .github/workflows/
```

### 7.5 Service layer and WebSocket API (console contract)

RoutineManager and SummaryCoordinator are the only places with behavior. Platforms, actions, triggers, conditions, Repairs fix flows and WebSocket commands call them and never each other (P16). The commands below ship in Phase 3 so the console (Phase 4) and any dashboard card can be built without touching the integration again; the Technical spec defines the payloads.

| Command | Purpose | Admin |
| --- | --- | --- |
| `device_routines/routines/list` | Every managed routine with settings, status, next action, Schedule items and conflicts | No |
| `device_routines/routines/get` | One device | No |
| `device_routines/routines/set` | A partial settings update for one device, validated by the compiler | Yes |
| `device_routines/routines/action` | `skip_next`, `pause`, `resume`, `enable` or `disable` for a native target (device, area, label, entity; `all` reserved for a later version) | Yes |
| `device_routines/devices/opt` | List eligible and suggested devices; opt devices in or out | Yes |
| `device_routines/schedule/today` | The house timeline for the Today view | No |
| `device_routines/settings/get` and `set` | The global settings of Section 10.4 | Yes for set |
| `device_routines/maintenance` | `clean_up_now`, `rebuild_index`, `reinstall_blueprint`, `refresh_summaries`, with a dry run | Yes |
| `device_routines/subscribe` | Pushes `routine_changed`, `schedule_changed`, `settings_changed` and `health_changed` | No |

## 8. Managed automation identity

A routine automation is recognizable at a glance in every place HA shows automations, and the integration decides ownership from two markers that a person cannot add by accident.

### 8.1 Markers

| # | Marker | Value | Kind | Where a person sees it |
| --- | --- | --- | --- | --- |
| M1 | Automation id | `device_routines_<12 hex>` | **Authoritative** | Automation settings, `automations.yaml` |
| M2 | Blueprint | `use_blueprint.path: device_routines/device_routine.yaml` | **Authoritative** | Editor shows the blueprint form; automation list filter by blueprint |
| M3 | Alias | `Routine: <device name>` | Presentation | Automation list (all routines sort together), device page Automations card, logbook, traces |
| M4 | Description | "Managed by Device Routines. Change it on the \<device name> device page or in this form. Take control to turn it into a normal automation." | Presentation | Top of the editor |
| M5 | Category | `Device Routines` (automation scope) | Presentation | Automation list grouped by category |
| M6 | Label | `Routines`, icon `mdi:calendar-clock` | Presentation | Label chip in the automation list; label filter |
| M7 | Icon | `mdi:calendar-clock` on the automation entity | Presentation | Automation list, device page Automations card |
| M8 | Entity id | `automation.routine_<device slug>` | Presentation | Anywhere entity ids show |
| M9 | Area | The device's area (P1, option, default on) | Presentation | Area pages |

Rules:

- **Ownership requires both M1 and M2.** Everything else is presentation. A hand written automation that happens to share an alias, label or category is never treated as a routine, and a test proves it.
- **The integration writes only to owned automations.** `ha_adapter` refuses any write whose target lacks M1 and M2, independently of the caller, so a bug elsewhere cannot touch a hand written automation.
- **Presentation markers are set on create and respected afterwards.** The alias follows device renames only while it still matches the generated pattern; once a person changes it, it is theirs. Removing the category, label or icon is allowed and does not affect ownership.
- **Duplicates are not routines.** Duplicating a routine in the editor gives a new id without M1, so the copy is a normal automation. The Schedule sensor lists it as "Automation".
- **Hand written automations always look different.** No marker is ever added to an automation the integration does not own, except the explicit conversion in FR-M1, which marks the original as replaced.

### 8.2 What happens when people change things

| Action outside the device page | Integration response |
| --- | --- |
| Edits inputs in the blueprint form | Sync back (Section 7.3) |
| Edits the entry in `automations.yaml` and reloads | Same as a form edit |
| Turns the automation off or on | The Routine switch follows |
| Deletes the automation | Treated as clearing the routine: settings reset, device stays opted in, no Repairs issue |
| Takes control (detaches from the blueprint) | No longer owned. Routine controls show unavailable; Schedule lists it as "Detached routine". One Repairs issue explains it and offers "Create a new routine", which never touches the detached automation |
| Restores `automations.yaml` from git | Ownership index rebuilt from M1 and M2 on reload; entities follow the restored inputs |
| Edits the installed blueprint file | Detected by file hash. Repairs offers "Restore the shipped blueprint"; nothing is overwritten without that click |
| Removes the integration | Removal follows the On removal setting (Section 10.4, default keep), because Home Assistant's removal dialog cannot ask. Keep runs "take control" on each routine so it becomes a standalone automation with the description "Formerly managed by Device Routines", then removes the blueprint once nothing uses it |
| Removes the device from Home Assistant | The routine is turned off at once; the automation and its helpers are deleted after the cleanup period (Section 10.4); no issue is raised |
| Renames the target entity id | The blueprint input is rewritten to the new id and the automation reloaded; no issue is raised |

### 8.3 Converting hand written automations

**FR-M1 (P2).** The parser recognizes hand written automations whose behavior exactly matches a routine for a single device (for example two time triggers that turn one switch on and off). Each match becomes a fixable Repairs issue: "\<alias> can become a routine on \<device>", showing both summaries side by side. Confirming creates the routine, turns the original off, and adds the label `Replaced by routine` to it. The original is never deleted or edited beyond that, so undo is turning it back on. Partial matches are never offered.

## 9. Runtime semantics

All runtime behavior lives in one blueprint and a few native helpers, so a routine behaves the same whether or not the integration is loaded.

### 9.1 Blueprint shape

- **Inputs**, in collapsible sections: Target (entity), Schedule (on time, off time, days, optional schedule helper), Timers (turn off after, turn back on after, timer helper), Behavior (catch up, respect manual changes, override switch, paused until entity), Advanced (pulse, late start window, only when conditions). Every input has a plain language name and description, because the blueprint form is the second editor.
- **Triggers**, each with an id: `scheduled_on`, `scheduled_off` (time, or schedule helper block start and end), `ha_start`, `reconnect` (target back from unavailable for 10 s), `device_on`, `device_off`, `timer_done` (purpose specific `timer.finished`), `pause_changed`, pause\_ended, `pulse`. Unused triggers are switched off with `enabled:` bound to inputs (ASSUMPTION A8).
- **Actions**: one `choose` keyed by trigger id; each branch carries the precedence rules of Section 5.2 as native conditions.
- **Mode** `queued`, max 10, so a burst of events is processed in order.
- Every branch and condition carries a `note:` explaining why it exists, so a trace reads like documentation.

v1.1 note: the note on each branch and condition is written as the `alias` key, which is what Home Assistant shows in traces. The `enabled` key on time triggers is paired with a valid sentinel value, because a disabled trigger is still schema validated (Technical spec 5.2).

### 9.2 Durations that survive restarts

Turn off after, Turn back on after and Pulse never use `for:` clauses, whose clocks reset on every restart and every unavailable blip. Instead each routine that needs a duration gets one timer helper, `timer.routine_<device slug>`, with restore enabled, labeled `Routines`, created by the integration (ASSUMPTION A5). The automation starts it on the triggering change, cancels it when the device changes back, and acts on `timer.finished`. A timer that expires while HA is down finishes at startup (ASSUMPTION A5b). A pause (Paused until) pauses running routine timers and resumes them when it ends.

### 9.3 Telling manual changes apart

Home Assistant contexts cannot answer "was this change manual?" on their own. A change caused by an automation carries the automation run's context, and that context has a parent only when the run was itself triggered by a state or event. A run started by a time, sun, timer or start trigger creates a parentless context, exactly like a wall switch does, so a template on the context parent would mark the routine's own scheduled turn on as manual. Attribution therefore lives in the integration, not in the blueprint (D26): `attribution.py` subscribes to `automation_triggered` and `script_started` events and keeps a bounded map of run context ids (24 hours, at most 10,000 entries). A state change on a routine's target entity is attributed as `automation` when its context id or parent id is in the map, as `user` when the context carries a user id (app, dashboard, voice assistant), and otherwise as `device` (wall switch, physical button, the device's own timer). User and device changes are manual. The classifier is validated in Stage 0 against recorded events from each protocol, including a time triggered automation (V3, A9 as amended).

Manual override is an integration owned, restored `switch` entity per device. The integration turns it on when a manual change leaves the device in a state the schedule did not ask for, and off when a manual change restores it; the managed automation turns it off whenever a scheduled time runs, and runs catch up when a person turns it off. Its `last_change_source` attribute names what changed the device last. If the integration is disabled, the entity is unavailable and the blueprint treats it as off, so routines degrade to plain schedules rather than stopping, and the blueprint needs no template for this.

### 9.4 Catch up

- **Windows** (both times set, or a schedule helper): on `ha_start` and `reconnect`, if not paused and no override, set the device to the state the window expects now.
- **One shot actions** (only one time set, such as a vacuum start): if HA starts within the late start window after a missed time (default 15 minutes, P1), run the action once, subject to its guards. Outside the window, wait for the next day.
- Catch up never fires a refused action and never runs twice for the same scheduled time.

### 9.5 Skip and pause at runtime

- **Stored state.** Paused until is an integration owned, restored `datetime` entity per device. The blueprint receives its entity id as an input. Pause values live in those entities, never in blueprint inputs, so pausing never rewrites `automations.yaml` or creates a git diff.
- **One check.** Every scheduled and countdown branch starts with the same native check: Paused until is not in the future. Time conditions and time triggers must accept a `datetime` entity (ASSUMPTION A13); if they do not, Paused until becomes a timestamp `sensor` set through the actions, with identical behavior.
- **Ending.** The `pause_ended` trigger fires at the Paused until value and runs catch up per D20. Resume sets the value to now, which takes the same path.
- **Skipping.** The integration computes the skip target with the same pure next run logic that writes the Schedule sentence, so what is skipped is exactly what the user saw. Computing a skip needs the integration; an existing pause holds and ends correctly without it, because the blueprint only reads stored values.
- **Visibility.** When a branch is skipped, the blueprint fires `device_routines_action_skipped` with device, action and scheduled time, then stops. The trace shows why.

Expectation for A13 (v1.1): current core time triggers and time conditions list `input_datetime` entities and sensors with the timestamp device class, not the `datetime` domain, so V12 is expected to fail for the trigger. The fallback is designed in advance: the per branch pause check becomes one unit tested template condition, and the integration schedules the pause end itself and calls the resume path. Without the integration an existing pause still ends correctly, because every scheduled trigger re evaluates the check; only the catch up at the exact pause end waits for the next scheduled time.

### 9.6 Load and scale

One automation per opted in device, entirely event driven: no `time_pattern` polling and no integration side timers. A home with 100 routines adds 100 automations and at most 100 timer helpers. The Schedule sensors recompute only on the events in FR-S7.

## 10. Data model and storage

A routine is fully described by its automation's blueprint inputs in `automations.yaml`; the integration's own storage holds only indexes and caches that can be rebuilt.

### 10.1 Routine settings (blueprint inputs)

```yaml
RoutineSettings:
  target_entity: <entity_id>
  on_time: "HH:MM" | null
  off_time: "HH:MM" | null
  days: every_day | weekdays | weekends | custom
  schedule_helper: <schedule entity_id> | null      # when days = custom
  turn_off_after_min: int (0 = off)
  turn_back_on_after_min: int (0 = off)
  timer_helper: <timer entity_id> | null            # created when a duration is set
  catch_up: bool (default true)
  late_start_window_min: int (default 15)
  respect_manual: bool (default true)
  override_switch: <switch entity_id>
  paused_until_entity: <datetime entity_id>         # FR-R12; the value is never stored here
  pulse: {at: "HH:MM", minutes: int, min_steady_min: 5} | null
  guards: [native conditions]                       # domain built ins plus Only when
```

### 10.2 Integration store

`.storage/device_routines` (HA `Store`, schema version 1, migrations tested):

| Key | Contents | Rebuildable from |
| --- | --- | --- |
| `owned` | automation id to {device id, target entity, last written config hash, last valid inputs} | Markers M1 and M2 plus current inputs |
| `opted_in` | device ids | The `Routines` device label |
| `blueprint_hash` | hash of the installed blueprint | The shipped file |
| `ai_cache` | config hash to {text, created} | Regenerated on demand |
| `opted_out_at` | device id to timestamp, for Remove unused routines | n/a (losing it only delays cleanup) |

### 10.3 Git and helpers

- `automations.yaml` holds every routine, so a git tracked config sees each routine change as an ordinary diff with a readable alias and description.
- Timer and schedule helpers live in HA storage, not YAML. If a referenced helper is missing (for example after restoring only `automations.yaml`), the integration recreates it with the same entity id and raises no issue. A recreated schedule helper starts empty and raises a Repairs issue asking for the weekly blocks.
- No secret, token or credential is ever stored. Diagnostics redact entity ids, device names, area names and aliases with `async_redact_data`, keeping only domains and shapes.

### 10.4 Global settings

Global settings live in the config entry options, so they survive restores, show in the options flow and are exposed through the WebSocket API for the console. Changing a default never rewrites existing routines; defaults apply when a routine is created. Every setting has a translation key and a one line description.

| Setting | Key | Values | Default |
| --- | --- | --- | --- |
| Schedule sensor scope | `schedule_scope` | all, routines, none | all |
| Time format | `time_format` | auto, 12h, 24h | auto (12 hour when the Home Assistant country uses it, else 24 hour) |
| Catch up after restart, default for new routines | `default_catch_up` | on, off | on |
| Respect manual changes, default for new routines | `default_respect_manual` | on, off | on |
| Late start window, default for new routines | `default_late_start_window_min` | 0 to 180 minutes | 15 |
| Clean up after | `cleanup_after_days` | 0 (never) to 365 | 30 |
| Put routines in the device's area | `assign_area` | on, off | on |
| On removal | `on_removal` | keep, delete | keep |
| AI summary entity | `ai_task_entity` | an AI Task entity or none | none |
| AI calls per hour | `ai_calls_per_hour` | 1 to 100 | 20 |
| Offer to convert matching automations | `offer_conversions` | on, off | on |
| Raise Repairs issues for conflicts | `raise_conflict_repairs` | on, off | on |

Maintenance actions (the hub button, the console, the WebSocket API and the `device_routines.maintenance` action): `clean_up_now`, `rebuild_index`, `reinstall_blueprint` and `refresh_summaries`. All are idempotent and safe to run at any time.

## 11. Repository, distribution and deployment

The repository is public and generic; Home Assistant gets new code only by pulling it from GitHub, through HACS for releases and through the deploy tool for development builds.

### 11.1 Repository and HACS packaging

- Public GitHub repository `ha-device-routines`, MIT license, description and topics (`home-assistant`, `hacs`, `automation`, `blueprint`, `schedule`, `timer`).
- `hacs.json`: `{"name": "Device Routines", "render_readme": true, "homeassistant": "2026.10.0", "zip_release": true, "filename": "device_routines.zip"}`.
- `manifest.json`: `domain`, `name`, `version`, `codeowners`, `documentation`, `issue_tracker`, `config_flow: true`, `integration_type: service`, `iot_class: local_push`, dependencies and after dependencies per Section 7.4.
- `brand/icon.png` and `brand/logo.png`; PR to `home-assistant/brands` before HACS default submission.
- Releases: tag `vX.Y.Z`, workflow builds the Phase 3 panel bundle, zips `custom_components/device_routines`, publishes notes from `CHANGELOG.md`, and refuses to release if the manifest version differs from the tag. Pre releases use `vX.Y.Z-beta.N`.
- Branches: `main` protected, receives merges from `dev` only with green CI. Conventional commits. Every behavior change updates docs, translations and `quality_scale.yaml` in the same PR.

### 11.2 How Home Assistant pulls updates

**Stable channel (HACS).** The repository is added to HACS as a custom repository, later submitted to the HACS default list. A new GitHub release appears as an update entity in Home Assistant; users install it from the UI or let HACS auto update, then restart. Jayant's instance stays on the development channel until v1.0.0 and then switches to HACS; the deploy tool warns when it finds a HACS managed install.

**Development channel: Home Assistant pulls by itself (D29).** Code reaches Home Assistant only by Home Assistant pulling it from GitHub. Nothing is copied from a laptop and nobody runs a deploy by hand.

1. Claude Code pushes to `dev`. CI runs every gate of Section 12.
2. On green, the CI workflow moves the `dev-stable` tag to that commit. The tag is the only thing the instance ever reads, so a red commit can never be deployed.
3. A `rest` sensor in Home Assistant polls the GitHub API for the `dev-stable` tag every 10 minutes (six unauthenticated calls per hour, far under the limit). When the sha changes, an automation calls `shell_command.deploy_device_routines` with `response_variable`.
4. `tools/ha_deploy.py` (standard library only, vendored identically in `ha-device-links`, D15) lives once at `/config/tools/` and is wired to three `shell_command` entries: `deploy_device_routines` (the `dev-stable` tag by default, or a given ref), `rollback_device_routines` and `device_routines_deploy_status`. Deploy resolves the ref, downloads the immutable commit archive over HTTPS (no token; the repository is public), extracts only `custom_components/device_routines`, syntax checks it with `compileall`, backs up the current directory (keeps 5), swaps atomically and writes `.deployed` with `{commit, branch, deployed_at, previous_commit, changed_files}`. It is idempotent: a ref already deployed returns `changed: false` and nothing else happens.
5. It prints one JSON object: `{ok, changed, commit, previous_commit, changed_files, restart_required, reload_automations, browser_reload}`. Python, manifest, translation and `services.yaml` changes set `restart_required`; a blueprint only change sets `reload_automations`, which the automation applies with `automation.reload`; a console bundle only change sets `browser_reload`. It never restarts Home Assistant, never reloads the config entry, never touches `.storage` or `automations.yaml`.
6. **Restart policy (D30).** By default the automation creates one persistent notification ("Device Routines \<sha> deployed; restart Home Assistant to load it") and stops. An opt in switch, `input_boolean.device_routines_auto_restart`, with a maintenance window (default 03:00 to 04:00) lets the instance restart itself when a deploy is pending, at most once per deploy. The switch stays off until Jayant turns it on.
7. **Post restart check.** On Home Assistant start, if `.deployed` is newer than the last successful load and the Health sensor is still unavailable after three minutes, the automation runs `rollback_device_routines` and notifies. The tool refuses a second rollback without a successful deploy in between, so there is no loop.
8. All of this ships in the repository as `tools/ha_package/device_routines_dev.yaml` (a Home Assistant package) and `tools/ha_deploy.py`; installing those two files is the one time bootstrap in Phase 0 of the Implementation plan.

**Claude Code's loop** (also written into `CLAUDE.md`):

1. Local tests, lint, type check and the privacy check pass; commit on `dev`; push. CI runs and, on green, moves `dev-stable`.
2. Either wait for the poll or trigger `shell_command.deploy_device_routines` through the HA MCP server with `return_response`, and report the commit and changed files.
3. If `restart_required`, say so and **stop. Never call `ha_restart` or `homeassistant.restart`, and never reload the entry as a substitute.** Jayant restarts, or the opt in window does.
4. After the restart, poll the hub Health sensor until its `commit` attribute equals the pushed sha, then run the read only live suite and check Repairs.
5. If the deploy is bad: `rollback_device_routines`, tell Jayant a restart is needed, write a regression test.

### 11.3 Keeping instance data out of the public repository

Instance data is anything that describes a real home: entity ids, device ids, device, area and floor names, automation aliases and text, IPs, hostnames, MAC addresses, URLs, usernames, tokens, and HA version plus hardware combinations from a real system.

| Mechanism | What it does |
| --- | --- |
| `.gitignore` first | The first commit contains only `.gitignore` covering `CLAUDE.local.md`, `local/`, `*.local.*`, `.env`, captured raw fixtures |
| `CLAUDE.local.md` | Private instance context for Claude Code, created from this document's Instance context tab. Never committed |
| `local/` | Raw captures from the live instance, the anonymization map, the denylist |
| `tools/anonymize.py` | Turns raw captures into fixtures with deterministic fake ids and names (`switch.example_plug_1`, "Example plug 1", "Area 1"); keeps times, domains and shapes; stores the mapping in `local/` |
| `tools/privacy_check.py` | Runs as a pre commit hook (staged files and the commit message) and in CI. Locally it checks against `local/denylist.txt`, generated from the instance's entity, device and area registries. In CI, where no denylist exists, it checks generic patterns: HA access tokens, GitHub tokens, private IPv4 ranges, MAC addresses, `.local` hostnames, email addresses, and 32 character hex ids outside anonymized fixtures. An allowlist covers intentional examples |
| Docs and examples | Generic names only ("living room fan", "robot vacuum"). Never a real home's names, even the author's |
| Live tests | Read entity ids and the HA URL from environment variables and `local/`, never from committed files |
| Issues and diagnostics | Issue templates ask reporters to attach redacted diagnostics; diagnostics redact by default (Section 10.3) |

### 11.4 Claude instruction files

- **`CLAUDE.md` (public):** purpose and links to `docs/PRD.md` and `docs/stage0-report.md`; architecture invariants (pure modules never import HA; only `ha_adapter.py` touches internals; only owned automations are written; storage changes need a migration and a test); safety rules (never restart HA, write probes need approval, refused actions are untouchable); commands; the deploy loop; coding standards (mypy strict, ruff, translations for every string, no em dash anywhere, conventional commits); the privacy rules of Section 11.3; the decision register pointer.
- **`CLAUDE.local.md` (private):** everything in the Instance context tab: the live HA version, the sandbox device, existing automations used as test material, AI Task availability, repository owner, and how to reach the HA MCP server.

v1.1: `CLAUDE.md` also links `docs/TECH_SPEC.md` and `docs/IMPLEMENTATION_PLAN.md`, carries the rules of engagement from the plan's Section 0, and describes the automatic pull loop of Section 11.2 so Claude Code never deploys by hand.

## 12. Testing strategy

The riskiest code is the blueprint, so it gets a behavior matrix run inside a real Home Assistant test harness, with every row of Section 5.2 covered by at least one test.

| Layer | Tooling | Covers | In CI |
| --- | --- | --- | --- |
| Pure units | pytest, Hypothesis | Compiler for every domain and option combination; refusals for every input (property: no generated input ever yields a refused action); markers; next run including weekdays, midnight crossing and DST dates; conflicts | Yes |
| Golden summaries | pytest with an anonymized corpus in `tests/fixtures/automations/` | Parser output line by line; corpus covers windows, weekday starts with guards, `for:` failsafes, keep alive, morning pulses, presence logic and template heavy automations that must read as custom logic | Yes |
| Round trip | Hypothesis | For any valid settings, the parser's summary of the compiled routine equals the sentence generated from the settings | Yes |
| Blueprint behavior | `pytest-homeassistant-custom-component`, time travel, restore state fixtures | Each Section 5.2 rule; restart with a running timer; reconnect; manual change (context without parent) versus another automation's change; pause and resume; late start window; refused actions never fire | Yes |
| Integration | Same harness, temporary config directory | Config and options flows, label sync, entities per domain, write path into `automations.yaml`, sync back, ownership guard against lookalike automations, take control, deletion, removal flow, helper creation and recreation, skip and pause actions with device, area and label targets, integration triggers and conditions, Repairs | Yes |
| Console (Phase 4) | vitest | Routines, Today and Settings views; contract tests against the WebSocket API | Yes |
| Live, read only | `pytest -m live`, token and URL from environment | Schedule sensors exist where expected; owned automations carry all markers; share of `source: none` lines; Health commit matches the deploy | No (run by Claude Code after each deploy) |
| Live, write | Manual, per item approval | Acceptance scenarios on the sandbox device named in `CLAUDE.local.md` | No |

CI gates: ruff, mypy strict, coverage of at least 95%, hassfest, HACS action, blueprint schema validation, the privacy check, an em dash check across the repository, a deploy tool parity check against ha-device-links, and the promotion job that moves the dev-stable tag only when every other job is green (Section 11.2).

## 13. Stage 0 validation and delivery

Stage 0 closes fourteen assumptions before any product code; the Schedule summary ships next because it is read only, then routines.

### 13.1 Assumptions

| ID | Assumption |
| --- | --- |
| A1 | An integration can install a blueprint into `<config>/blueprints/automation/device_routines/` at setup, and HA picks it up with a blueprint reload, no restart |
| A2 | A stable write path exists from integration code for UI automations: it writes `automations.yaml` with the same locking as the editor, and reloading one automation does not restart the others |
| A3 | HA's reference helpers find automations that target a device's entities directly, through the device, its area or a label, including YAML defined automations |
| A4 | The loaded automation entity exposes its full config for both UI and YAML automations |
| A5 | Timer and schedule helpers can be created from integration code with a chosen entity id and label. A5b: a restored timer that expired while HA was down fires `timer.finished` at startup |
| A6 | Schedule helper blocks that meet at midnight do not cause an off/on blip in block start and end triggers |
| A7 | Time trigger behavior on DST skipped and repeated times is known and documented |
| A8 | Blueprints can switch triggers off with `enabled:` bound to inputs, offer a `condition` selector, and use collapsible input sections |
| A9 | Amended in v1.1: automation caused changes do not reliably carry a parent context (time, sun, timer and start triggers create parentless runs), so the assumption now reads: every automation and script run emits an event carrying the context its actions will use, and physical, app and voice changes never reuse such a context. Validated by replaying V3 recordings through the attribution classifier (Section 9.3) |
| A10 | Entities from this integration attach to existing devices from other integrations and appear in their Configuration card (proven approach in Device Links; reconfirm on the current HA version) |
| A11 | "Take control" keeps the automation id and removes `use_blueprint` |
| A12 | `ai_task.generate_data` is available and usable with a locally hosted model |
| A13 | Time triggers and time conditions accept a datetime domain entity, and a restored datetime entity keeps its value across restarts. Expected to fail for the trigger on current core (Section 9.5); the fallback is designed and V12 records which path applies |
| A14 | A custom integration can register purpose specific triggers and conditions that appear in the automation editor with device, area and label targets |

### 13.2 Stage 0 items

Read only items are pre approved. **WRITE** items need Jayant's approval per item, with a read before and a read proving restoration after. Throwaway artifacts are named `stage0_*` and removed at the end.

Note: since 2026-10-17 WRITE items no longer need a per item approval; the read before and the read after stay (decision L26, `docs/decisions-log.md`).

| ID | Item | Write? | Closes |
| --- | --- | --- | --- |
| V1 | Repository skeleton, `.gitignore` first, CI (hassfest, HACS, pytest, mypy, ruff, privacy check, em dash check) green on an empty integration | No | P1, P2 |
| V2 | Read automation configs and reference results for every automation on the live instance; save anonymized fixtures; record how YAML automations appear | No | A3, A4 |
| V3 | Capture `state_changed` contexts while Jayant operates a Z-Wave, a Zigbee, a Matter and a Wi-Fi device by hand, by app and by voice, and while an automation changes them | No | A9 |
| V4 | Check AI Task availability and a sample `generate_data` call against a non instance prompt | No | A12 |
| V5 | Install a `stage0_` blueprint from a throwaway integration; validate inputs, sections, `condition` selector and `enabled:` binding | **WRITE** (config files) | A1, A8 |
| V6 | Create, update and delete one `stage0_` automation through the candidate write path; confirm other automations keep running (watch their `current` runs and last triggered) | **WRITE** | A2 |
| V7 | Create and delete a `stage0_` timer and schedule helper from integration code | **WRITE** | A5 |
| V8 | Take control of the `stage0_` blueprint automation; confirm id and config shape | **WRITE** | A11 |
| V9 | Attach a `stage0_` config entity to the sandbox device; confirm placement on its device page; remove it | **WRITE** | A10 |
| V10 | Harness tests: restored expired timer, midnight adjacent schedule blocks, DST dates | No (test harness only) | A5b, A6, A7 |
| V11 | Deploy loop round trip with the generalized tool: push a trivial change, deploy, Jayant restarts, Health shows the commit, roll back | **WRITE** (adds `shell_command` entries) | P3 |
| V12 | Harness tests: a time trigger and a time condition against a datetime entity; a restored datetime entity across a restart | No (test harness only) | A13 |
| V13 | Register a stage0 trigger and condition from the V5 throwaway integration; confirm they appear in the automation editor pickers with device, area and label targets | WRITE (config files) | A14 |

v1.1 amendments to this table: V1 is now Phase 0 of the Implementation plan and must be complete before any probe runs. V3 additionally records the `automation_triggered` and `script_started` events around each change, including a change made by a time triggered `stage0_` automation, so the attribution map of Section 9.3 is validated against parentless contexts. V11 now proves the automatic pull: push a trivial change, watch CI move `dev-stable`, watch the instance deploy it with no further action, restart, see Health, roll back. V12 also records the fallback path when the `datetime` domain is not accepted.

Exit: all read only items done, every WRITE item done or explicitly deferred by Jayant, every assumption closed or amended in `docs/stage0-report.md`, fixtures committed only after anonymization.

### 13.3 Phases

&#91;embedded content: delivery roadmap · Stage 0 and four phases, five gates\]

Scope per phase (v1.1; the Implementation plan tab is authoritative and adds tasks, tests, validation steps and exit criteria to each). **Phase 0:** public repository, CI gates, privacy tooling, the deploy tool and the Home Assistant package, a skeleton integration with the hub Health sensor; proves the GitHub to Home Assistant pull loop end to end. **Stage 0:** validation probes V2 to V13 and `docs/stage0-report.md`. **Phase 1:** FR-S1 to S4, S7, S8, the hub device, the global settings scaffold, options; v0.1.0. **Phase 2:** all P0 (FR-R1, R3, R5, R6, R11 to R15), the blueprint, the compiler, attribution, device page entities including Skip next, Paused until and Resume, the skip and pause actions, the write path, sync back, markers M1 to M8, refusals, the self healing of Section 3.1, removal; v0.2.0. **Phase 3:** all P1 (FR-R2, R4, R8, R17), the late start window, the AI summary, conflicts, marker M9, the complete settings catalog, the WebSocket API of Section 7.5; v0.3.0. **Phase 4:** all P2 (FR-R9, R10, FR-M1), the console with its Routines, Today and Settings views, the brands PR, the HACS default submission; v1.0.0. **Future, not scheduled:** the calendar view, including vacation handling (Section 5.7).

### 13.4 Acceptance scenarios

| ID | Scenario | Pass criteria |
| --- | --- | --- |
| S1 | Open a device that a hand written weekday automation starts | Schedule reads the next start; attributes list the automation with `kind: automation` |
| S2 | Set Turn on at 17:00 and Turn off at 09:00 on the sandbox device | Done in under 60 seconds; one automation with M1 to M8; Schedule reads correctly in both periods |
| S3 | Stop HA at 16:55, start at 17:10 | Device on within 60 seconds of startup |
| S4 | Turn the device on by hand at noon, restart HA at 12:30 | Device stays on with Manual override on; at 17:00 the routine runs and the override clears |
| S5 | Turn off after 30; turn on at 10:00; restart at 10:20 | Device off at 10:30 |
| S6 | Change Turn off at in the blueprint form; then set a refused action in the form | First change appears on the device page; second turns the routine off and raises a Repairs issue; nothing overwritten |
| S7 | Take control of a routine; separately create a hand automation with the same alias, label and category | Detached handling per Section 8.2; the lookalike is never written |
| S8 | Remove the integration choosing keep | Every routine is a standalone automation that still runs |
| S9 | Offer conversion for a hand written on/off pair | Repairs shows both summaries; confirming creates the routine and turns the original off |
| S10 | Stage a commit containing a denylisted name; push a branch containing a token shaped string | The pre commit hook blocks the first; CI fails the second |
| S11 | Press Skip next at 15:00 on the sandbox device with a 17:00 to 09:00 window | Device stays off tonight; the sentence reads Skipped, on \<next day> 5:00 PM; the action\_skipped event and trigger fire at 17:00; the next day's window runs normally |
| S12 | At 16:30 call device\_routines.pause for 2 hours targeting the sandbox device's area; restart HA at 17:15 | No turn on at 17:00; the pause survives the restart; at 18:30 catch up turns the device on (D20) |
| S13 | From a dashboard button, call skip\_next on a label that covers one routine device and one plain device | The routine device skips; the plain device is listed as ignored in the response; no error |

## 14. Decision register and risks

Every decision has a default; Claude Code proceeds on the default unless Jayant answers otherwise, and records which applied.

### 14.1 Decisions

**Resolved 2026-10-13:** D18 to D23 and D25 accepted as listed. D24 decided by Jayant: no house wide pause in v1; vacation handling moves to the calendar view. D1 to D17 stand at their defaults. **v1.1 (2026-10-13):** D26 to D34 added at their defaults; D16 is superseded by D31 (the Today panel becomes one view of the console); D12 is unchanged in effect but implemented as the On removal setting (Section 10.4).

| ID | Decision | Options | Default | Why |
| --- | --- | --- | --- | --- |
| D1 | Name and domain | `device_routines` "Device Routines"; `routines`; `device_schedules` | `device_routines` | Says what it is in HACS search; avoids colliding with HA's generic word "routine" in voice assistants |
| D2 | Reaching HA internals (automation writes, helper creation, automation configs) | (a) core internals through one version guarded adapter; (b) HA's own WebSocket API over loopback with a dedicated token | (a), with (b) as the fallback if A2 or A5 fail | (a) matches how the editor writes and needs no stored credential; (b) is stable but adds a secret |
| D3 | Execution layer | (a) blueprint instances; (b) fully generated standalone automations; (c) an integration side scheduler | (a) | Recognizable (M2), one place for logic, form editing that syncs back, no drift, runs without the integration. (b) creates drift on every hand edit; (c) puts the integration in the runtime path |
| D4 | Automations per device | One per device; one per option | One per device | One thing to find, read and trace per device |
| D5 | Opt in | Label, options picker and setup suggestions; or every eligible device automatically | Opt in | Adding controls to hundreds of devices nobody asked about is the opposite of low cognitive load |
| D6 | Schedule sensor scope | All devices with automations; routine devices only; none | All devices with automations | It is the feature that explains existing automations |
| D7 | Duration mechanism | Timer helper with restore; integration owned timestamp sensor plus startup reconcile | Timer helper | Native, restart safe, visible, already familiar to HA users |
| D8 | Respect manual changes default | On; off | On | Matches what people expect after flipping a switch |
| D9 | Catch up default | On; off | On | Missed transitions are the most common silent failure of hand written schedules |
| D10 | Keep alive versus manual changes | Keep alive wins; manual wins | Keep alive wins | Its only purpose is to undo offs |
| D11 | AI summary | Opt in; off entirely | Opt in, off by default | Useful, but sends automation logic to a model, so it must be a conscious choice |
| D12 | Removal behavior | Keep routines as standalone automations; delete them | Keep | Never destroy working behavior silently |
| D13 | Refused actions | Section 5.4 list | As listed | Adding or removing one requires a register entry |
| D14 | Minimum HA version | Validated version; one minor behind current | Validated version at first release, then never more than one minor behind current | Stability over novelty (P13) |
| D15 | Deploy tool sharing | Same file vendored in both repos; a separate small repo | Vendored, identical, version header, checked by CI | No new repo to maintain; drift between copies is caught |
| D16 | Today panel | Phase 4, read only; never | Phase 4, read only | Valuable for the whole house view; configuration stays on device pages |
| D17 | License | MIT; Apache 2.0 | MIT | Matches Device Links and common HACS practice |
| D18 | Skip next when the next action is a window start | Skip the whole occurrence (start and its end); skip only the start | Whole occurrence | "Skip tonight" is what people mean; skipping only the start leaves a stray off that could cut short a manual on |
| D19 | Skip next when the next action is a window end or a running countdown | Skip it (device stays as is until the following action); make Skip next unavailable in these cases | Skip it, with the sentence showing the consequence (for example Skipped, off Fri 9:00 AM) | Skip always means the action the sentence shows; "keep it on this time" is a common need for countdowns |
| D20 | When a pause or skip ends inside a window | Catch up now; wait for the next scheduled action | Catch up now when Catch up is on | Same rule as after a restart, so there is one behavior to learn |
| D21 | Manual changes while paused | Allowed without setting Manual override; reverted | Allowed, no override | A pause means the routine keeps its hands off, not that the device is locked |
| D22 | Skip and pause scope | Routines only; also hand written automations that are purely time triggered, by turning them off and back on | Routines only; revisit in Phase 4 | Acting on unowned automations conflicts with P7 and silently drops their other triggers while off |
| D23 | Phase placement | Device skip, pause, resume, disable and actions in Phase 2, triggers and conditions in Phase 3; everything in Phase 3 | First option | Pausing is daily use from day one; triggers and conditions depend on A14 |
| D24 | House wide pause (Pause all switch, hub Paused until) | Both; one of them; neither in v1 | Neither in v1 (decided by Jayant) | Vacation handling needs more design; it moves to the future calendar view (Section 5.7, D25) |
| D25 | Calendar view (Section 5.7) | Design later; drop | Design later, not in any phase | Native and promising, and the future home for vacation handling (D24), but calendar writes need their own design |
| D26 | Manual change attribution | A template on the context parent in the blueprint; an integration side context map feeding the override switch | Integration side context map; the blueprint only reads the override switch | Time, sun, timer and start triggered runs create parentless contexts, so the template cannot tell the routine's own actions from a wall switch (Section 9.3) |
| D27 | Turn off after and Turn back on after on one routine | Both allowed with precedence rules; mutually exclusive | Mutually exclusive | Removes a whole class of interactions and the timer ambiguity; a device either auto offs or keeps alive |
| D28 | Cleanup of opted out and orphaned routines | A manual button after 30 days; automatic after a configurable period with the button kept | Automatic, default 30 days, 0 disables | Zero upkeep (P15); opting out was already explicit |
| D29 | How the development instance receives code | Claude Code triggers each deploy over MCP; Home Assistant polls a CI promoted dev-stable tag and deploys itself | Polling the dev-stable tag; the MCP trigger kept as an accelerator | A red commit can never deploy; no human or agent is in the loop for the pull |
| D30 | Restarting Home Assistant after a deploy | Always manual; an opt in automatic restart in a maintenance window | Manual by default; the opt in window stays off until Jayant enables it | Keeps Jayant's restart rule while allowing a fully unattended loop later |
| D31 | Future management UI | A Today panel only; a console with Routines, Today and Settings views on a WebSocket API shipped one phase earlier | Console on the Section 7.5 API; the API in Phase 3, the console in Phase 4 | Keeps the option open at near zero cost and makes every capability scriptable from day one |
| D32 | Time format in sentences | Always 12 hour; always 24 hour; follow the instance | Auto from the Home Assistant country, overridable in settings | A public integration cannot assume US clocks |
| D33 | Config flow | A suggestions checklist as part of setup; a zero field setup with the suggestions optional and repeatable in options | Zero fields, one optional skippable screen | Install should take one click (P15) |
| D34 | The same times on an arbitrary day set | Not offered; a Some days option with the day set edited in the routine form or the console | Some days | Sync back from the blueprint form already has to represent it |

### 14.2 Risks

| ID | Risk | Mitigation |
| --- | --- | --- |
| R1 | HA internals used for writes change between releases | One adapter, version guard, fast Repairs issue, live suite after each HA update, D2 fallback |
| R2 | The blueprint grows unreadable | Small option catalog, `note:` on every branch, behavior matrix tests, non goals enforced |
| R3 | A person edits a managed automation into an invalid state | Validation on sync back; routine off, nothing overwritten, one click restore |
| R4 | Context attribution differs by integration (A9) | Per protocol fixtures; worst case is a missed or false override, never a refused action; the option can be turned off per device |
| R5 | The parser misreads an automation | Never guesses; golden corpus; custom logic fallback; AI lines labeled |
| R6 | Instance data leaks into the public repo | `.gitignore` first commit, anonymizer, local denylist hook, CI patterns, generic docs |
| R7 | A write collides with someone saving in the automation editor | Same lock as the editor (A2), hash check before write, one retry, otherwise Repairs |
| R8 | Helper and automation clutter | One automation and at most one timer per device, all labeled `Routines` and grouped by category |
| R9 | HA ships native device level scheduling | Everything is already a standard automation; migration is take control; release notes watched monthly |
| R10 | GitHub API polling fails or the dev-stable tag goes stale | The instance simply keeps the deployed commit; Claude Code can trigger a deploy over MCP; Health shows the commit so the gap is visible |
| R11 | The attribution map misses a source (a new way to change devices) | Worst case is a false override, never a refused action; the override switch is visible and one tap clears it; Respect manual changes can be turned off per routine |

## 15. Appendix: glossary and references

| Term | Meaning |
| --- | --- |
| Routine | The set of options configured for one device, executed by one managed automation |
| Managed automation | An automation carrying markers M1 and M2; the only kind the integration writes |
| Hand written automation | Any other automation, including copies of managed ones; read for summaries, never written |
| Detached routine | A former managed automation after Take control; now hand written |
| Window | A period defined by both an on and an off time, or by schedule helper blocks |
| One shot action | A scheduled action with no opposite, such as a vacuum start |
| Manual change | A state change whose context has no parent automation or script |
| Manual override | The restored switch that suppresses catch up and keep alive until the next scheduled time |
| Catch up | Applying the expected state after a restart or reconnect |
| Keep alive | Turn back on after |
| Summary line | One sentence describing one action an automation takes on a device |
| Instance data | Anything describing a real home (Section 11.3); never in the public repository |
| Paused until | The single stored value behind skip and pause; while it is in the future, no scheduled action or countdown runs |
| Skip next | Pausing until just after the next action the Schedule sentence shows |

Prior art reviewed for the gap analysis in Section 1.1: [scheduler-component](https://github.com/nielsfaber/scheduler-component) and [scheduler-card](https://github.com/nielsfaber/scheduler-card), [Auto Off Timer](https://github.com/0x3333/light_timeout), [HA Simple Timer](https://github.com/RJay45/ha-simple-timer). Stage 0 consults the current HA developer docs for blueprints and selectors, automation configuration, the timer and schedule helpers, AI Task, entity and device registries, the Integration Quality Scale and HACS publishing requirements, and records the URLs and dates in the Stage 0 report.

## 16. Change log

- v1.1 (2026-10-13): zero maintenance guarantees (3.1) and principles P15 and P16; zero field config flow and automatic cleanup (4.1, D28, D33); the hub Routines sensor lists every managed routine and Health carries channel and status (4.4); the Today panel became a console on a WebSocket API (4.5, 7.5, D31); Turn off after and Turn back on after made mutually exclusive (D27); manual change attribution moved into the integration after finding that time triggered runs produce parentless contexts (9.3, A9, D26); the A13 expectation and its fallback stated (9.5); the global settings catalog including On removal (10.4); Home Assistant now pulls the CI promoted dev-stable tag by itself, with an opt in restart window (11.2, D29, D30); time format setting (D32); the Some days option (D34); Phase 0 added to the roadmap (13.3); goals G8 and G9; risks R10 and R11. The Technical spec and Implementation plan tabs were added.
- v1.0 (2026-10-13): first draft for Claude Code.
