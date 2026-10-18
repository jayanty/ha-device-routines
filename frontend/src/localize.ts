// The console's words and the integration's error messages (decision L62).
//
// The console's own words are the keys of translations/en.json, read through `t`. Every
// key appears in the source as a whole string literal (never assembled), so
// `localize.test.ts` can prove each one exists and none is unused. A refusal of the
// service layer renders its `code` with the integration's `exceptions` translations,
// which the core serves to the frontend once `loadBackendTranslation` has loaded them.

import type { HomeAssistant, LocalizeFunc } from "./api";
import { DOMAIN, isApiError } from "./api";
import en from "./translations/en.json";

type Leaves<T> = {
  [K in keyof T & string]: T[K] extends string ? K : `${K}.${Leaves<T[K]>}`;
}[keyof T & string];

/** Every key of translations/en.json, as a dotted path. */
export type Key = Leaves<typeof en>;

export type Placeholders = Record<string, string | number>;

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix = "", into: Map<string, string> = new Map()): Map<string, string> {
  for (const [name, value] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${name}` : name;
    if (typeof value === "string") {
      into.set(key, value);
    } else {
      flatten(value, key, into);
    }
  }
  return into;
}

const LANGUAGES: Record<string, Map<string, string>> = { en: flatten(en) };

function language(hass: HomeAssistant | undefined): string {
  const wanted = hass?.locale?.language ?? hass?.language ?? "en";
  return wanted in LANGUAGES ? wanted : wanted.split("-")[0] ?? "en";
}

/** Replace each `{name}` with its placeholder; an unknown name stays as written. */
export function format(text: string, placeholders: Placeholders = {}): string {
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in placeholders ? String(placeholders[name]) : whole,
  );
}

/** The console's text for `key` in the user's language, English when it has none. */
export function t(hass: HomeAssistant | undefined, key: Key, placeholders?: Placeholders): string {
  const strings = LANGUAGES[language(hass)] ?? LANGUAGES["en"];
  const text = strings?.get(key) ?? LANGUAGES["en"]?.get(key) ?? key;
  return format(text, placeholders);
}

/** Every key of the English file, for the tests. */
export function allKeys(): string[] {
  return [...(LANGUAGES["en"]?.keys() ?? [])];
}

// --------------------------------------------------------------------------------------
// Errors
// --------------------------------------------------------------------------------------

const loaded = new WeakMap<HomeAssistant, Promise<LocalizeFunc | undefined>>();

/** Load the integration's `exceptions` translations once per `hass` object. */
async function exceptionsLocalize(hass: HomeAssistant): Promise<LocalizeFunc> {
  let pending = loaded.get(hass);
  if (pending === undefined) {
    pending = hass.loadBackendTranslation?.("exceptions", DOMAIN) ?? Promise.resolve(undefined);
    loaded.set(hass, pending);
  }
  try {
    return (await pending) ?? hass.localize;
  } catch {
    return hass.localize;
  }
}

/** The setting a refusal is about, from its `setting` placeholder, so a form can mark it. */
export function errorSetting(error: unknown): string | undefined {
  return isApiError(error) ? (error.translation_placeholders?.["setting"] ?? undefined) : undefined;
}

/**
 * The user's text for a refusal: the integration's translation of its code with its
 * placeholders, else the error's own message (the core's errors, such as `unauthorized`,
 * have no translation of ours), else a generic sentence.
 */
export async function errorText(hass: HomeAssistant, error: unknown): Promise<string> {
  if (!isApiError(error)) {
    return t(hass, "common.error_unknown");
  }
  const localize = await exceptionsLocalize(hass);
  const key = `component.${DOMAIN}.exceptions.${error.code}.message`;
  const text = localize(key, error.translation_placeholders ?? {});
  return text && text !== key ? text : error.message || t(hass, "common.error_unknown");
}

