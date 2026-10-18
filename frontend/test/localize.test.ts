// The console's words: every key the source uses exists in translations/en.json, every
// key there is used, keys are never assembled at runtime, and no template carries a user
// visible literal (decision L62).

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

import { allKeys, errorSetting, errorText, format, t } from "../src/localize";
import en from "../src/translations/en.json";
import { makeHass } from "./fake-hass";

const SOURCE = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const SECTIONS = Object.keys(en);
const KEY = new RegExp(`^(?:${SECTIONS.join("|")})\\.[A-Za-z0-9_]+(?:\\.[A-Za-z0-9_]+)*$`);

function sources(directory = SOURCE): { path: string; text: string }[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return sources(path);
    }
    return entry.name.endsWith(".ts") ? [{ path, text: readFileSync(path, "utf8") }] : [];
  });
}

/** Every double quoted string literal of the source that has the shape of a key. */
function usedKeys(): Set<string> {
  const used = new Set<string>();
  for (const { text } of sources()) {
    for (const match of text.matchAll(/"((?:[^"\\\n]|\\.)*)"/g)) {
      const literal = match[1] ?? "";
      if (KEY.test(literal)) {
        used.add(literal);
      }
    }
  }
  return used;
}

// --------------------------------------------------------------------------------------
// A small reader of html`...` templates: their static parts, without the expressions
// --------------------------------------------------------------------------------------

function skipString(source: string, start: number): number {
  const quote = source[start];
  let index = start + 1;
  while (index < source.length && source[index] !== quote) {
    index += source[index] === "\\" ? 2 : 1;
  }
  return index + 1;
}

/** From just after `${`, the index just after its closing brace. */
function skipExpression(source: string, start: number): number {
  let depth = 1;
  let index = start;
  while (index < source.length) {
    const character = source[index];
    if (character === "'" || character === '"') {
      index = skipString(source, index);
      continue;
    }
    if (character === "`") {
      index = readTemplate(source, index + 1).end;
      continue;
    }
    if (character === "{") {
      depth += 1;
    } else if (character === "}") {
      depth -= 1;
      if (depth === 0) {
        return index + 1;
      }
    }
    index += 1;
  }
  throw new Error("unterminated expression");
}

/** From just after a backtick, the template's static parts and the index after it. */
function readTemplate(source: string, start: number): { statics: string[]; end: number } {
  const statics: string[] = [];
  let current = "";
  let index = start;
  while (index < source.length) {
    const character = source[index];
    if (character === "\\") {
      current += source.slice(index, index + 2);
      index += 2;
    } else if (character === "`") {
      statics.push(current);
      return { statics, end: index + 1 };
    } else if (character === "$" && source[index + 1] === "{") {
      statics.push(current);
      current = "";
      index = skipExpression(source, index + 2);
    } else {
      current += character;
      index += 1;
    }
  }
  throw new Error("unterminated template");
}

const VISIBLE_ATTRIBUTES = /\b(?:title|aria-label|placeholder|alt)\s*=\s*"([^"]*)"/g;

/** The user visible literal text of every html template in `source`. */
function templateLiterals(source: string): string[] {
  const found: string[] = [];
  let index = source.indexOf("html`");
  while (index !== -1) {
    const { statics } = readTemplate(source, index + 5);
    const markup = statics.join("\u0000").replace(/<!--[\s\S]*?-->/g, "");
    for (const tag of markup.match(/<[^>]*>/g) ?? []) {
      for (const attribute of tag.matchAll(VISIBLE_ATTRIBUTES)) {
        if (/[A-Za-z]/.test(attribute[1] ?? "")) {
          found.push(attribute[0]);
        }
      }
    }
    for (const piece of markup.replace(/<[^>]*>/g, "\u0000").split("\u0000")) {
      if (/[A-Za-z]/.test(piece)) {
        found.push(piece.trim());
      }
    }
    index = source.indexOf("html`", index + 5);
  }
  return found;
}

describe("translations/en.json", () => {
  test("every key used in src exists in en.json", () => {
    const keys = new Set(allKeys());

    expect([...usedKeys()].filter((key) => !keys.has(key))).toEqual([]);
  });

  test("no key of en.json is unused", () => {
    const used = usedKeys();

    expect(allKeys().filter((key) => !used.has(key))).toEqual([]);
  });

  test("no key is assembled at runtime", () => {
    const assembled = new RegExp(`\`(?:${SECTIONS.join("|")})\\.`);

    expect(sources().filter(({ text }) => assembled.test(text)).map(({ path }) => path)).toEqual([]);
  });

  test("no template carries a user visible literal", () => {
    const literals = sources().flatMap(({ path, text }) =>
      templateLiterals(text).map((literal) => `${path}: ${literal}`),
    );

    expect(literals).toEqual([]);
  });

  test("the template reader sees literals in text and in visible attributes", () => {
    const source = 'html`<p title="Hello">${x} <b>${y ? html`<i>Inner</i>` : "z"}</b> Plain</p>`';

    expect(templateLiterals(source)).toEqual(['title="Hello"', "Plain", "Inner"]);
  });

  test("every value is a non empty string", () => {
    expect(allKeys().length).toBeGreaterThan(0);
    for (const key of allKeys()) {
      expect(t(undefined, key as never), key).not.toBe("");
    }
  });
});

describe("t", () => {
  test("fills placeholders and keeps unknown ones", () => {
    expect(t(undefined, "routines.select_row", { device: "Desk lamp" })).toBe("Select Desk lamp");
    expect(format("{a} and {b}", { a: 1 })).toBe("1 and {b}");
  });

  test("falls back to English for a language the console does not have", () => {
    const hass = makeHass({ language: "xx-YY", locale: { language: "xx-YY" } });

    expect(t(hass, "panel.title")).toBe("Device Routines");
  });

  test("reads a regional variant as its language", () => {
    const hass = makeHass({ locale: { language: "en-GB" } });

    expect(t(hass, "panel.tabs.today")).toBe("Today");
  });
});

describe("errorText", () => {
  test("renders a code with the integration's exceptions translations", async () => {
    const hass = makeHass();
    const error = {
      code: "not_opted_in",
      message: "untranslated",
      translation_placeholders: { device: "Garage door" },
    };

    expect(await errorText(hass, error)).toBe(
      "Garage door has no routine controls. Add the Routines label to it, or choose it in the Device Routines options.",
    );
    expect(hass.loadBackendTranslation).toHaveBeenCalledWith("exceptions", "device_routines");
  });

  test("falls back to the error's message, then to a sentence of its own", async () => {
    const hass = makeHass();

    expect(await errorText(hass, { code: "unauthorized", message: "Unauthorized" })).toBe("Unauthorized");
    expect(await errorText(hass, { code: "unauthorized", message: "" })).toBe(t(hass, "common.error_unknown"));
    expect(await errorText(hass, new Error("boom"))).toBe(t(hass, "common.error_unknown"));
  });

  test("uses hass.localize when the translations cannot be loaded", async () => {
    const hass = makeHass();
    hass.loadBackendTranslation.mockRejectedValueOnce(new Error("offline"));

    expect(await errorText(hass, { code: "detached", message: "The routine is detached" })).toBe(
      "The routine is detached",
    );
  });

  test("names the setting a refusal is about", () => {
    expect(errorSetting({ code: "x", message: "y", translation_placeholders: { setting: "off_time" } })).toBe(
      "off_time",
    );
    expect(errorSetting({ code: "x", message: "y" })).toBeUndefined();
    expect(errorSetting("nope")).toBeUndefined();
  });
});
