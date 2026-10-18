// Extract the JSON examples of docs/api.md into test/fixtures/api.json (decision L62).
//
// Every fenced `json` block is filed under the second level heading it sits in, which
// for a command section is the command without its `device_routines/` prefix
// (`routines/list`). A block is a request when its `type` names a command, an event when
// it is an `event` message, an error when it carries a `code` (or is a failed `result`
// message, whose `error` is kept), and otherwise the response to the request before it.
// The output depends only on the document: keys in document order, two space indent, a
// final newline. `fixture.test.ts` keeps the committed file equal to a fresh extraction.
//
// Usage: node scripts/extract-api-fixture.mjs [docs/api.md] [test/fixtures/api.json]

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const COMMAND_PREFIX = "device_routines/";

// Paths from this file's directory. Not `new URL(path, import.meta.url)`: Vite rewrites
// that form into an asset URL when the tests import this file.
const HERE = dirname(fileURLToPath(import.meta.url));
export const DEFAULT_SOURCE = join(HERE, "..", "..", "docs", "api.md");
export const DEFAULT_TARGET = join(HERE, "..", "test", "fixtures", "api.json");

/**
 * @typedef {Record<string, unknown>} Json
 * @typedef {{ request: Json | null, response: Json | null }} Example
 * @typedef {{ examples: Example[], errors: Json[], events: Json[] }} Section
 * @typedef {Record<string, Section>} Fixture
 */

/**
 * Return the section key of a second level heading: its text without backticks,
 * lowercased, so a command section is the command as written (`routines/list`) and the
 * conventions section is `conventions`.
 *
 * @param {string} heading
 * @returns {string}
 */
function sectionKey(heading) {
  return heading.replaceAll("`", "").trim().toLowerCase();
}

/**
 * @param {unknown} value
 * @returns {value is Json}
 */
function isObject(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Extract every JSON example of the document, keyed by section.
 *
 * @param {string} markdown
 * @returns {Fixture}
 */
export function extract(markdown) {
  /** @type {Fixture} */
  const fixture = {};
  const lines = markdown.split("\n");
  let section = "";
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (line.startsWith("## ")) {
      section = sectionKey(line.slice(3));
      continue;
    }
    if (line.trim() !== "```json") {
      continue;
    }
    const start = index + 1;
    let end = start;
    while (end < lines.length && (lines[end] ?? "").trim() !== "```") {
      end += 1;
    }
    if (end >= lines.length) {
      throw new Error(`docs/api.md line ${index + 1}: unterminated json block`);
    }
    const text = lines.slice(start, end).join("\n");
    index = end;
    /** @type {unknown} */
    let value;
    try {
      value = JSON.parse(text);
    } catch (error) {
      throw new Error(`docs/api.md line ${start + 1}: ${String(error)}`, { cause: error });
    }
    if (!isObject(value)) {
      throw new Error(`docs/api.md line ${start + 1}: an example must be a JSON object`);
    }
    if (section === "") {
      throw new Error(`docs/api.md line ${start + 1}: an example before the first section`);
    }
    file(fixture, section, value);
  }
  return fixture;
}

/**
 * File one example under its section.
 *
 * @param {Fixture} fixture
 * @param {string} key
 * @param {Json} value
 */
function file(fixture, key, value) {
  const section = (fixture[key] ??= { examples: [], errors: [], events: [] });
  const type = value["type"];
  if (typeof type === "string" && type.startsWith(COMMAND_PREFIX)) {
    section.examples.push({ request: value, response: null });
  } else if (type === "event") {
    section.events.push(value);
  } else if (type === "result" && value["success"] === false && isObject(value["error"])) {
    section.errors.push(value["error"]);
  } else if (typeof value["code"] === "string") {
    section.errors.push(value);
  } else {
    const open = section.examples.findLast((example) => example.response === null);
    if (open === undefined) {
      section.examples.push({ request: null, response: value });
    } else {
      open.response = value;
    }
  }
}

/**
 * Render a fixture exactly as it is committed.
 *
 * @param {Fixture} fixture
 * @returns {string}
 */
export function render(fixture) {
  return `${JSON.stringify(fixture, null, 2)}\n`;
}

/**
 * Read the document and write the fixture.
 *
 * @param {string} source
 * @param {string} target
 */
export function main(source = DEFAULT_SOURCE, target = DEFAULT_TARGET) {
  writeFileSync(target, render(extract(readFileSync(source, "utf8"))));
}

if (process.argv[1] !== undefined && fileURLToPath(import.meta.url) === process.argv[1]) {
  main(process.argv[2], process.argv[3]);
}
