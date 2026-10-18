// A fake `hass` for the views: its connection answers every command of docs/api.md with
// the examples recorded in fixtures/api.json, a test can replace any answer, and every
// message sent is kept. Its `localize` serves the integration's own translations, the
// `exceptions` category only after `loadBackendTranslation` loaded it, as the core does.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { vi } from "vitest";

import type { Connection, HomeAssistant, LocalizeFunc, ManagerEvent, MessageBase, RoutineView } from "../src/api";
import fixtureJson from "./fixtures/api.json";

export type Json = Record<string, unknown>;

export interface Example {
  request: Json | null;
  response: Json | null;
}

export interface Section {
  examples: Example[];
  errors: Json[];
  events: Json[];
}

export const fixture = fixtureJson as unknown as Record<string, Section>;

export function section(name: string): Section {
  const found = fixture[name];
  if (found === undefined) {
    throw new Error(`docs/api.md has no example section ${name}`);
  }
  return found;
}

function example(name: string, index: number): Example {
  const found = section(name).examples[index];
  if (found === undefined) {
    throw new Error(`docs/api.md has no example ${index} under ${name}`);
  }
  return found;
}

/** A copy of a recorded request. */
export function request(name: string, index = 0): Json {
  const value = example(name, index).request;
  if (value === null) {
    throw new Error(`example ${index} under ${name} has no request`);
  }
  return structuredClone(value);
}

/** A recorded request as the console sends it: the connection adds the `id`. */
export function documented(name: string, index = 0): Json {
  const { id: _id, ...message } = request(name, index);
  return message;
}

/** A copy of a recorded response. */
export function response<T = Json>(name: string, index = 0): T {
  const value = example(name, index).response;
  if (value === null) {
    throw new Error(`example ${index} under ${name} has no response`);
  }
  return structuredClone(value) as T;
}

/** A copy of a recorded error. */
export function recordedError(name: string, index = 0): Json {
  const value = section(name).errors[index];
  if (value === undefined) {
    throw new Error(`no error ${index} under ${name}`);
  }
  return structuredClone(value);
}

/** A copy of the recorded routines, the living room fan first. */
export function routines(): RoutineView[] {
  return response<{ routines: RoutineView[] }>("routines/list").routines;
}

const PREFIX = "device_routines/";

/** The index of each `devices/opt` example in docs/api.md, in the document's order. */
export const DEVICES_OPT = { list: 0, suggest: 1, in: 2, out: 3 } as const;

type Handler = (message: MessageBase) => unknown;

function withSeconds(value: unknown): unknown {
  return typeof value === "string" && /^\d{2}:\d{2}$/.test(value) ? `${value}:00` : value;
}

/** The answers the fixture gives; commands without a recorded answer are derived from one. */
function recordedAnswer(message: MessageBase, list: () => RoutineView[]): unknown {
  const command = message.type.slice(PREFIX.length);
  switch (command) {
    case "routines/list":
      return { routines: list() };
    case "routines/get": {
      const found = list().find((routine) => routine.device_id === message["device_id"]);
      if (found === undefined) {
        throw recordedError("routines/get");
      }
      return found;
    }
    case "routines/set": {
      const found = list().find((routine) => routine.device_id === message["device_id"]);
      if (found === undefined) {
        throw recordedError("routines/get");
      }
      const patch = Object.fromEntries(
        Object.entries(message["settings"] as Json).map(([key, value]) => [key, withSeconds(value)]),
      );
      return { ...found, settings: { ...found.settings, ...patch } };
    }
    case "routines/action":
      return response("routines/action");
    case "devices/opt": {
      const op = message["op"];
      if (op === "list") {
        return response("devices/opt", DEVICES_OPT.list);
      }
      if (op === "suggest") {
        return response("devices/opt", DEVICES_OPT.suggest);
      }
      if (op === "in") {
        return response("devices/opt", DEVICES_OPT.in);
      }
      const ids = message["device_id"] as string[];
      return { results: ids.map((id) => ({ device_id: id, opted_in: false, changed: true, view: null })) };
    }
    case "schedule/today": {
      const day = response<Json>("schedule/today");
      return typeof message["date"] === "string" ? { ...day, date: message["date"] } : day;
    }
    case "settings/get":
      return response("settings/get");
    case "settings/set":
      return { ...response<Json>("settings/get"), ...(message["settings"] as Json) };
    case "maintenance": {
      const report = response<{ action: string; would_change: string[] }>("maintenance");
      return message["dry_run"] === true
        ? { ...report, action: message["action"] }
        : { action: message["action"], changed: report.would_change, would_change: [] };
    }
    default:
      throw { code: "unknown_command", message: "Unknown command." };
  }
}

interface Subscription {
  callback: (event: ManagerEvent) => void;
  message: MessageBase;
  active: boolean;
}

export class FakeConnection implements Connection {
  readonly sent: MessageBase[] = [];
  readonly subscriptions: Subscription[] = [];
  private readonly handlers = new Map<string, Handler>();
  /** The routines `routines/list` and `routines/get` answer with; a test may replace them. */
  routines: RoutineView[] = routines();

  /** Answer `command` with `handler` from now on; a handler that throws is a refusal. */
  answer(command: string, handler: Handler): void {
    this.handlers.set(`${PREFIX}${command}`, handler);
  }

  async sendMessagePromise<T>(message: MessageBase): Promise<T> {
    this.sent.push(structuredClone(message));
    await Promise.resolve();
    const handler = this.handlers.get(message.type);
    const answer =
      handler === undefined ? recordedAnswer(message, () => structuredClone(this.routines)) : await handler(message);
    return structuredClone(answer) as T;
  }

  async subscribeMessage<T>(callback: (event: T) => void, message: MessageBase): Promise<() => void> {
    this.sent.push(structuredClone(message));
    const subscription: Subscription = {
      callback: callback as unknown as (event: ManagerEvent) => void,
      message,
      active: true,
    };
    this.subscriptions.push(subscription);
    return () => {
      subscription.active = false;
    };
  }

  /** Push an event to every live subscription. */
  emit(event: ManagerEvent): void {
    for (const subscription of this.subscriptions) {
      if (subscription.active) {
        subscription.callback(structuredClone(event));
      }
    }
  }

  /** The messages sent for one command, in order. */
  sentOf(command: string): MessageBase[] {
    return this.sent.filter((message) => message.type === `${PREFIX}${command}`);
  }
}

// --------------------------------------------------------------------------------------
// The integration's translations, as the core serves them to the frontend
// --------------------------------------------------------------------------------------

type Tree = { [key: string]: string | Tree };

function flatten(tree: Tree, prefix: string, into: Map<string, string>): Map<string, string> {
  for (const [name, value] of Object.entries(tree)) {
    const key = `${prefix}.${name}`;
    if (typeof value === "string") {
      into.set(key, value);
    } else {
      flatten(value, key, into);
    }
  }
  return into;
}

const REPOSITORY = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const INTEGRATION = JSON.parse(
  readFileSync(join(REPOSITORY, "custom_components", "device_routines", "translations", "en.json"), "utf8"),
) as Tree;

export const BACKEND = flatten(INTEGRATION, "component.device_routines", new Map());

function localizeWith(strings: Map<string, string>): LocalizeFunc {
  return (key, values = {}) =>
    (strings.get(key) ?? "").replace(/\{(\w+)\}/g, (whole, name: string) =>
      name in values ? String(values[name]) : whole,
    );
}

export type FakeHass = HomeAssistant & {
  connection: FakeConnection;
  loadBackendTranslation: ReturnType<typeof vi.fn<(category: string, integration: string) => Promise<LocalizeFunc>>>;
};

/** A fake `hass` of the synthetic home of docs/api.md. */
export function makeHass(overrides: Partial<HomeAssistant> = {}): FakeHass {
  const loadedStrings = new Map<string, string>();
  const localize = localizeWith(loadedStrings);
  const hass: FakeHass = {
    connection: new FakeConnection(),
    states: {},
    areas: {
      living_room: { area_id: "living_room", name: "Living room" },
      kitchen: { area_id: "kitchen", name: "Kitchen" },
    },
    devices: {
      dev_living_room_fan: { id: "dev_living_room_fan", name: "Living room fan", name_by_user: null },
      dev_desk_lamp: { id: "dev_desk_lamp", name: "Desk lamp", name_by_user: null },
    },
    language: "en",
    locale: { language: "en", time_format: "12" },
    localize,
    loadBackendTranslation: vi.fn(async (category: string, integration: string) => {
      for (const [key, value] of BACKEND) {
        if (key.startsWith(`component.${integration}.${category}.`)) {
          loadedStrings.set(key, value);
        }
      }
      return localize;
    }),
    ...overrides,
  } as FakeHass;
  return hass;
}

// --------------------------------------------------------------------------------------
// The DOM
// --------------------------------------------------------------------------------------

interface Updating {
  updateComplete: Promise<unknown>;
}

function descendants(root: ParentNode, into: Element[] = []): Element[] {
  for (const element of root.querySelectorAll("*")) {
    into.push(element);
    if (element.shadowRoot !== null) {
      descendants(element.shadowRoot, into);
    }
  }
  return into;
}

/** Wait until every pending answer arrived and every element below `root` rendered it. */
export async function settle(root: Element = document.body): Promise<void> {
  for (let round = 0; round < 8; round += 1) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    const elements = [root, ...descendants(root.shadowRoot ?? root)];
    await Promise.all(
      elements
        .filter((element): element is Element & Updating => "updateComplete" in element)
        .map((element) => element.updateComplete),
    );
  }
}

/** Mount an element on the page with a fake `hass`, and let it load. */
export async function mount<T extends HTMLElement & { hass: HomeAssistant | undefined }>(
  tag: string,
  hass: FakeHass,
  setup: (element: T) => void = () => undefined,
): Promise<T> {
  const element = document.createElement(tag) as T;
  setup(element);
  element.hass = hass;
  document.body.appendChild(element);
  await settle(element);
  return element;
}

/** The element's shadow root, which every console element has. */
export function shadow(element: Element): ShadowRoot {
  if (element.shadowRoot === null) {
    throw new Error(`${element.tagName} has no shadow root`);
  }
  return element.shadowRoot;
}

/** The one element matching `selector`, or a failing test. */
export function one<T extends Element = HTMLElement>(root: ParentNode, selector: string): T {
  const found = root.querySelector(selector) as T | null;
  if (found === null) {
    throw new Error(`nothing matches ${selector}`);
  }
  return found;
}

/** The text of an element with its whitespace collapsed. */
export function text(element: Element | ShadowRoot | null | undefined): string {
  return (element?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/** Set a form control's value as a person would, and send its change event. */
export function change(control: HTMLInputElement | HTMLSelectElement, value: string | boolean): void {
  if (typeof value === "boolean" && control instanceof HTMLInputElement) {
    control.checked = value;
  } else {
    control.value = String(value);
  }
  control.dispatchEvent(new Event("input", { bubbles: true }));
  control.dispatchEvent(new Event("change", { bubbles: true }));
}
