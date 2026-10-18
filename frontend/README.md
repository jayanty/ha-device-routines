# Device Routines console

The sidebar panel of Device Routines (PRD 4.5): the Routines, Today and Settings views,
built with Lit and TypeScript into one ES module by Vite and tested with vitest. The
source lives here, outside the integration, so the release zip and the dev channel carry
only the bundle (decision L62).

## Commands

Node 22.12 or later. Run them in this directory.

```bash
npm ci                    # the exact dependency tree of package-lock.json
npm run typecheck         # tsc --noEmit, strict
npm test                  # vitest in a DOM environment (happy-dom)
npm run build             # the bundle, see below
npm run extract-fixture   # rewrite test/fixtures/api.json from docs/api.md
```

`npm run build` writes `custom_components/device_routines/frontend/dist/device-routines-panel.js`,
the one file the panel loads. Git ignores that path until the integration registers the
panel and a CI check compares the committed bundle with a fresh build.

## What the console may use

- Data comes only from `hass.connection.sendMessagePromise` and
  `hass.connection.subscribeMessage` with the commands and payloads of `docs/api.md`, and
  from `hass.states` for the Health sensor (`sensor.device_routines_health`). Area names
  come from `hass.areas` and device names from `hass.devices` when present, else the id.
  `src/api.ts` mirrors the Types section of `docs/api.md`.
- The panel element is `device-routines-panel`; it takes the `hass`, `narrow`, `route`
  and `panel` properties the core gives a custom panel and shows `dr-routines-view`,
  `dr-today-view` or `dr-settings-view`. It holds the console's one `subscribe`
  subscription: `routine_changed` refreshes that routine, `schedule_changed` the Today
  view, `settings_changed` the Settings view and `health_changed` the Health block, each
  when its view is open. The subscription ends when the panel leaves the page.
- An error renders its `code` through
  `hass.localize("component.device_routines.exceptions.<code>.message", placeholders)`
  after `hass.loadBackendTranslation("exceptions", "device_routines")`, falling back to
  the error's `message`; a `setting` placeholder marks the field of an inline edit.
- The console introduces no semantics of its own (PRD P16): every control is one command,
  and the service layer validates and decides.
- Colors and spacing come only from Home Assistant theme variables, each with a fallback.
  No `ha-*` element is needed.

## Words

Every word the console shows is a key of `src/translations/en.json`, read through `t` in
`src/localize.ts`. A key is always written whole as a string literal, never assembled, so
`test/localize.test.ts` proves that every key used exists, that no key is unused and that
no template holds a literal of its own. Values of the API (statuses, verbs, days) map to
keys in `src/labels.ts`.

## Tests

`test/fake-hass.ts` is a fake `hass` whose connection answers every command with the JSON
examples of `docs/api.md`, extracted by `scripts/extract-api-fixture.mjs` into
`test/fixtures/api.json`. The extraction files each example under its `##` section: a
request, the response after it, an error or an event. `test/fixture.test.ts` keeps the
committed fixture equal to a fresh extraction, so when `docs/api.md` changes, run
`npm run extract-fixture` and commit both. The fake's `localize` serves the integration's
own `translations/en.json`, so a test sees the message a person would.

## Dependencies

Exact versions only, each published at least two weeks before it is added. The lock file
was resolved with `npm install --before=<date>` so every transitive package meets the same
rule; use it the same way when updating.
