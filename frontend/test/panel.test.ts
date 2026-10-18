// The panel: the three views, the one subscription and where its events go.

import { afterEach, describe, expect, test, vi } from "vitest";

import type { ManagerEvent, PanelRoute } from "../src/api";
import { HEALTH_ENTITY } from "../src/api";
import "../src/device-routines-panel";
import type { DeviceRoutinesPanel } from "../src/device-routines-panel";
import type { FakeHass } from "./fake-hass";
import type { Json } from "./fake-hass";
import { documented, makeHass, mount, one, response, section, settle, shadow, text } from "./fake-hass";

afterEach(() => {
  document.body.replaceChildren();
});

async function panel(
  hass: FakeHass = makeHass(),
  route?: PanelRoute,
): Promise<{ hass: FakeHass; element: DeviceRoutinesPanel; root: ShadowRoot }> {
  const element = await mount<DeviceRoutinesPanel>("device-routines-panel", hass, (created) => {
    created.route = route;
    created.panel = { url_path: "device-routines", title: "Device Routines", config: null };
  });
  return { hass, element, root: shadow(element) };
}

async function show(element: DeviceRoutinesPanel, view: string): Promise<void> {
  one<HTMLButtonElement>(shadow(element), `nav button[data-view="${view}"]`).click();
  await settle(element);
}

function openView(root: ShadowRoot): string | undefined {
  return root.querySelector("main")?.firstElementChild?.tagName.toLowerCase();
}

function event(kind: ManagerEvent["kind"], deviceId: string | null = null): ManagerEvent {
  return { kind, device_id: deviceId, reason: null, data: null };
}

describe("the views", () => {
  test("opens on Routines and switches between the three views", async () => {
    const { element, root } = await panel();

    expect(text(one(root, "h1"))).toBe("Device Routines");
    expect(openView(root)).toBe("dr-routines-view");
    expect(one(root, 'nav button[data-view="routines"]').getAttribute("aria-selected")).toBe("true");

    await show(element, "today");
    expect(openView(root)).toBe("dr-today-view");
    expect(one(root, 'nav button[data-view="today"]').getAttribute("aria-selected")).toBe("true");

    await show(element, "settings");
    expect(openView(root)).toBe("dr-settings-view");

    await show(element, "routines");
    expect(openView(root)).toBe("dr-routines-view");
  });

  test("the route picks the view, and a tab moves the route", async () => {
    const changed = vi.fn();
    window.addEventListener("location-changed", changed);
    const { element, root } = await panel(makeHass(), { prefix: "/device-routines", path: "/today" });

    expect(openView(root)).toBe("dr-today-view");
    await show(element, "today");
    expect(changed).not.toHaveBeenCalled();
    await show(element, "settings");
    window.removeEventListener("location-changed", changed);

    expect(window.location.pathname).toBe("/device-routines/settings");
    expect(changed).toHaveBeenCalledOnce();

    element.route = { prefix: "/device-routines", path: "/routines" };
    await settle(element);
    expect(openView(root)).toBe("dr-routines-view");
    element.route = { prefix: "/device-routines", path: "/unknown" };
    await settle(element);
    expect(openView(root)).toBe("dr-routines-view");
  });

  test("each view gets hass and narrow", async () => {
    const { element, root } = await panel();
    element.narrow = true;
    await settle(element);

    const view = one(root, "dr-routines-view") as HTMLElement & { hass: unknown; narrow: boolean };
    expect(view.hass).toBe(element.hass);
    expect(view.narrow).toBe(true);
  });

  test("a narrow panel has a menu button that opens the sidebar", async () => {
    const { element, root } = await panel();
    expect(root.querySelector("button.menu")).toBeNull();

    element.narrow = true;
    await settle(element);
    const toggled = vi.fn();
    element.addEventListener("hass-toggle-menu", toggled);
    one<HTMLButtonElement>(root, "button.menu").click();

    expect(toggled).toHaveBeenCalledOnce();
    expect(one(root, "button.menu").getAttribute("aria-label")).toBe("Open the sidebar");
  });
});

describe("the time format", () => {
  test("the views get the integration's Time format, read again after settings_changed", async () => {
    const hass = makeHass({ locale: { language: "en", time_format: "12" } });
    hass.connection.answer("settings/get", () => ({ ...response<Json>("settings/get"), time_format: "24h" }));
    const { element, root } = await panel(hass);
    const next = (): string => text(one(shadow(one(root, "dr-routines-view")), '[data-cell="next"]'));

    expect((one(root, "dr-routines-view") as HTMLElement & { timeFormat: unknown }).timeFormat).toBe("24h");
    expect(next()).toBe("On Mon 17:00");
    await show(element, "today");
    expect((one(root, "dr-today-view") as HTMLElement & { timeFormat: unknown }).timeFormat).toBe("24h");
    await show(element, "settings");
    expect((one(root, "dr-settings-view") as HTMLElement & { timeFormat: unknown }).timeFormat).toBe("24h");
    await show(element, "routines");

    hass.connection.answer("settings/get", () => response<Json>("settings/get"));
    hass.connection.emit(event("settings_changed"));
    await settle(element);
    expect(next()).toBe("On Mon 5:00 PM");
  });

  test("a refused settings read leaves the views on the user's profile", async () => {
    const hass = makeHass({ locale: { language: "en", time_format: "24" } });
    hass.connection.answer("settings/get", () => {
      throw { code: "not_loaded", message: "x" };
    });
    const { root } = await panel(hass);

    expect((one(root, "dr-routines-view") as HTMLElement & { timeFormat: unknown }).timeFormat).toBeUndefined();
    expect(text(one(shadow(one(root, "dr-routines-view")), '[data-cell="next"]'))).toBe("On Mon 17:00");
  });
});

describe("subscribe", () => {
  test("subscribes once per panel, whatever hass updates arrive", async () => {
    const { hass, element } = await panel();

    element.hass = { ...hass } as FakeHass;
    await settle(element);
    element.hass = hass;
    await settle(element);

    expect(hass.connection.sentOf("subscribe")).toEqual([documented("subscribe")]);
    expect(hass.connection.subscriptions.filter((subscription) => subscription.active)).toHaveLength(1);
  });

  test("routine_changed refreshes that routine in the Routines view", async () => {
    const { hass, element } = await panel();

    const recorded = section("subscribe").events[0] as { event: ManagerEvent };
    hass.connection.emit({ ...recorded.event, device_id: "dev_living_room_fan" });
    await settle(element);

    expect(hass.connection.sentOf("routines/get")).toEqual([
      { type: "device_routines/routines/get", device_id: "dev_living_room_fan" },
    ]);
    expect(hass.connection.sentOf("schedule/today")).toEqual([]);
  });

  test("schedule_changed refreshes the Today view", async () => {
    const { hass, element } = await panel();
    await show(element, "today");
    expect(hass.connection.sentOf("schedule/today")).toHaveLength(1);

    hass.connection.emit(event("schedule_changed"));
    await settle(element);

    expect(hass.connection.sentOf("schedule/today")).toHaveLength(2);
    expect(hass.connection.sentOf("routines/get")).toEqual([]);
  });

  test("settings_changed refreshes the Settings view and health_changed its Health block", async () => {
    const hass = makeHass({
      states: { [HEALTH_ENTITY]: { entity_id: HEALTH_ENTITY, state: "ok", attributes: {} } },
    });
    const { element } = await panel(hass);
    await show(element, "settings");
    // One read for the panel's time format, one for the view.
    expect(hass.connection.sentOf("settings/get")).toHaveLength(2);

    hass.connection.emit(event("settings_changed"));
    await settle(element);
    expect(hass.connection.sentOf("settings/get")).toHaveLength(4);

    const view = shadow(one(shadow(element), "dr-settings-view"));
    expect(text(one(view, '[data-health="state"]'))).toBe("OK");
    hass.states[HEALTH_ENTITY] = { entity_id: HEALTH_ENTITY, state: "degraded", attributes: {} };
    hass.connection.emit(event("health_changed"));
    await settle(element);
    expect(text(one(view, '[data-health="state"]'))).toBe("Degraded");
  });

  test("an event for a view that is not open sends nothing", async () => {
    const { hass, element } = await panel();
    const before = hass.connection.sent.length;

    hass.connection.emit(event("health_changed"));
    hass.connection.emit(event("routine_changed"));
    await settle(element);

    expect(hass.connection.sent).toHaveLength(before);
  });

  test("schedule_changed reads the conversion offers again while the Routines view is open", async () => {
    const { hass, element } = await panel();
    const before = hass.connection.sent.length;

    hass.connection.emit(event("schedule_changed"));
    await settle(element);

    expect(hass.connection.sent.slice(before)).toEqual([{ type: "device_routines/conversions/list" }]);
  });

  test("settings_changed reads the time format again, whichever view is open", async () => {
    const { hass, element } = await panel();
    const before = hass.connection.sent.length;

    hass.connection.emit(event("settings_changed"));
    await settle(element);

    expect(hass.connection.sent.slice(before)).toEqual([{ type: "device_routines/settings/get" }]);
  });

  test("the subscription ends when the panel is removed, and a panel put back subscribes again", async () => {
    const { hass, element } = await panel();
    const [subscription] = hass.connection.subscriptions;

    element.remove();
    await settle(document.body);
    expect(subscription?.active).toBe(false);

    document.body.appendChild(element);
    await settle(element);
    expect(hass.connection.sentOf("subscribe")).toHaveLength(2);
    expect(hass.connection.subscriptions.filter((item) => item.active)).toHaveLength(1);
  });

  test("a panel removed before its subscription answers still ends it", async () => {
    const hass = makeHass();
    let resolve: (unsubscribe: () => void) => void = () => undefined;
    const unsubscribe = vi.fn();
    hass.connection.subscribeMessage = (() =>
      new Promise((done) => {
        resolve = done;
      })) as typeof hass.connection.subscribeMessage;
    const element = document.createElement("device-routines-panel");
    element.hass = hass;
    document.body.appendChild(element);
    element.remove();

    resolve(unsubscribe);
    await settle(document.body);

    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  test("a refused subscription leaves the panel working", async () => {
    const hass = makeHass();
    hass.connection.subscribeMessage = (() => Promise.reject({ code: "unknown_command", message: "x" })) as never;
    const { element, root } = await panel(hass);

    await show(element, "today");
    expect(openView(root)).toBe("dr-today-view");
    element.remove();
  });
});
