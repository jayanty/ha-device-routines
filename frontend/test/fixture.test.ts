// The recorded payloads stay equal to docs/api.md: the committed fixture is a fresh
// extraction of the document, so an API change that updates the document and not the
// fixture (or the other way round) fails here.

import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";

import { DEFAULT_SOURCE, DEFAULT_TARGET, extract, render } from "../scripts/extract-api-fixture.mjs";
import { DEVICES_OPT } from "./fake-hass";

const COMMANDS = [
  "routines/list",
  "routines/get",
  "routines/set",
  "routines/action",
  "devices/opt",
  "schedule/today",
  "settings/get",
  "settings/set",
  "maintenance",
  "subscribe",
];

describe("fixtures/api.json", () => {
  test("the committed fixture equals a fresh extraction of docs/api.md", () => {
    const fresh = render(extract(readFileSync(DEFAULT_SOURCE, "utf8")));

    expect(readFileSync(DEFAULT_TARGET, "utf8")).toBe(fresh);
  });

  test("the devices/opt examples are where the fake looks for them", () => {
    const fixture = extract(readFileSync(DEFAULT_SOURCE, "utf8"));
    const examples = fixture["devices/opt"]?.examples ?? [];

    for (const [op, index] of Object.entries(DEVICES_OPT)) {
      expect(examples[index]?.request?.["op"], op).toBe(op);
      expect(examples[index]?.response, op).not.toBeNull();
    }
  });

  test("every command of docs/api.md has its request example", () => {
    const fixture = extract(readFileSync(DEFAULT_SOURCE, "utf8"));

    for (const command of COMMANDS) {
      const types = fixture[command]?.examples.map((example) => example.request?.["type"]);
      expect(types, command).toContain(`device_routines/${command}`);
    }
  });
});

describe("extract", () => {
  const block = (value: unknown): string => ["```json", JSON.stringify(value), "```"].join("\n");

  test("pairs each response with the request before it, under its section", () => {
    const markdown = [
      "# Title",
      "## `a/b`",
      block({ type: "device_routines/a/b", op: "x" }),
      block({ answer: 1 }),
      block({ type: "device_routines/a/b", op: "y" }),
      "## c",
      block({ answer: 2 }),
    ].join("\n");

    expect(extract(markdown)).toEqual({
      "a/b": {
        examples: [
          { request: { type: "device_routines/a/b", op: "x" }, response: { answer: 1 } },
          { request: { type: "device_routines/a/b", op: "y" }, response: null },
        ],
        errors: [],
        events: [],
      },
      c: { examples: [{ request: null, response: { answer: 2 } }], errors: [], events: [] },
    });
  });

  test("files errors and events apart from the examples", () => {
    const error = { code: "nope", message: "No" };
    const markdown = [
      "## Conventions",
      block({ id: 1, type: "result", success: false, error }),
      block(error),
      block({ id: 1, type: "event", event: { kind: "schedule_changed" } }),
    ].join("\n");

    expect(extract(markdown)).toEqual({
      conventions: {
        examples: [],
        errors: [error, error],
        events: [{ id: 1, type: "event", event: { kind: "schedule_changed" } }],
      },
    });
  });

  test("ignores blocks that are not json and refuses broken ones", () => {
    expect(extract("## a\n```yaml\nx: 1\n```\n")).toEqual({});
    expect(() => extract("## a\n```json\n{\n")).toThrow(/unterminated/);
    expect(() => extract("## a\n```json\n{nope}\n```\n")).toThrow(/line 3/);
    expect(() => extract("## a\n```json\n[1]\n```\n")).toThrow(/JSON object/);
    expect(() => extract("```json\n{}\n```\n")).toThrow(/before the first section/);
  });

  test("renders with two spaces and a final newline", () => {
    expect(render({})).toBe("{}\n");
    expect(render(extract(`## a\n${block({ answer: 1 })}`))).toContain('\n  "a": {\n');
  });
});
