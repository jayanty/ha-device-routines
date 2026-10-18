// The Settings view against the recorded payloads of docs/api.md.

import { afterEach, describe, expect, test } from "vitest";

import type { GlobalSettings, HassEntity } from "../src/api";
import { HEALTH_ENTITY, MAINTENANCE_ACTIONS } from "../src/api";
import "../src/views/settings-view";
import type { DrSettingsView } from "../src/views/settings-view";
import type { FakeHass, Json } from "./fake-hass";
import { change, documented, makeHass, mount, one, recordedError, response, settle, shadow, text } from "./fake-hass";

afterEach(() => {
  document.body.replaceChildren();
});

function health(state = "ok", attributes: Record<string, unknown> = {}): HassEntity {
  return {
    entity_id: HEALTH_ENTITY,
    state,
    attributes: {
      version: "1.0.0",
      commit: "abc1234",
      branch: "dev",
      deployed_at: "2026-10-19T08:00:00+00:00",
      channel: "dev",
      blueprint_schema: 2,
      blueprint_status: "ok",
      owned_count: 1,
      loaded_count: 1,
      issues: [],
      ha_version: "2026.10.2",
      last_reconcile: null,
      ...attributes,
    },
  };
}

interface Mounted {
  hass: FakeHass;
  element: DrSettingsView;
  root: ShadowRoot;
}

async function view(hass: FakeHass = makeHass()): Promise<Mounted> {
  const element = await mount<DrSettingsView>("dr-settings-view", hass);
  return { hass, element, root: shadow(element) };
}

function control<T extends HTMLElement = HTMLInputElement>(root: ParentNode, key: string): T {
  return one<T>(root, `[data-setting="${key}"] [name="${key}"]`);
}

describe("settings/get", () => {
  test("shows every setting with an editor fitting its type", async () => {
    const { hass, root } = await view();
    const settings = response<GlobalSettings>("settings/get");

    expect(hass.connection.sentOf("settings/get")).toEqual([documented("settings/get")]);
    expect([...root.querySelectorAll("[data-setting]")].map((field) => field.getAttribute("data-setting"))).toEqual(
      Object.keys(settings),
    );
    for (const [key, value] of Object.entries(settings)) {
      const editor = control<HTMLInputElement>(root, key);
      if (typeof value === "boolean") {
        expect([editor.tagName, editor.type, editor.checked], key).toEqual(["INPUT", "checkbox", value]);
      } else if (typeof value === "number") {
        expect([editor.tagName, editor.type, editor.value], key).toEqual(["INPUT", "number", String(value)]);
      } else if (key === "ai_task_entity") {
        expect([editor.tagName, editor.type, editor.value], key).toEqual(["INPUT", "text", ""]);
      } else {
        expect([editor.tagName, editor.value], key).toEqual(["SELECT", value]);
      }
    }
    expect(text(one(root, '[data-setting="time_format"]'))).toContain("Time format");
    expect([...control<HTMLSelectElement>(root, "time_format").options].map((option) => option.value)).toEqual([
      "auto",
      "12h",
      "24h",
    ]);
  });

  test("a setting the console does not know yet is edited by its value's type", async () => {
    const hass = makeHass();
    hass.connection.answer("settings/get", () => ({
      ...response<Json>("settings/get"),
      future_flag: true,
      future_count: 3,
      future_text: "x",
    }));
    const { root } = await view(hass);

    expect(control(root, "future_flag").type).toBe("checkbox");
    expect(control(root, "future_count").type).toBe("number");
    expect(control(root, "future_text").value).toBe("x");
    expect(text(one(root, '[data-setting="future_flag"]'))).toBe("future_flag");
  });
});

describe("settings/set", () => {
  test("sends only the changed keys", async () => {
    const { hass, element, root } = await view();
    const save = one<HTMLButtonElement>(root, 'button[data-action="save"]');

    expect(save.disabled).toBe(true);
    change(control<HTMLSelectElement>(root, "time_format"), "24h");
    await settle(element);
    one<HTMLButtonElement>(root, 'button[data-action="save"]').click();
    await settle(element);

    expect(hass.connection.sentOf("settings/set")).toEqual([documented("settings/set")]);
    expect(text(one(root, '[role="status"]'))).toBe("Settings saved.");
    expect(one<HTMLButtonElement>(root, 'button[data-action="save"]').disabled).toBe(true);
  });

  test("every kind of editor sends its value in the settings' own form", async () => {
    const { hass, element, root } = await view();

    change(control(root, "default_catch_up"), false);
    change(control(root, "cleanup_after_days"), "60");
    change(control(root, "ai_calls_per_hour"), "");
    change(control(root, "ai_task_entity"), " ai_task.local_model ");
    change(control<HTMLSelectElement>(root, "on_removal"), "delete");
    await settle(element);
    one<HTMLButtonElement>(root, 'button[data-action="save"]').click();
    await settle(element);

    expect(hass.connection.sentOf("settings/set")[0]?.["settings"]).toEqual({
      default_catch_up: false,
      cleanup_after_days: 60,
      ai_task_entity: "ai_task.local_model",
      ai_calls_per_hour: "",
      on_removal: "delete",
    });
  });

  test("a change back to the stored value sends nothing", async () => {
    const { hass, element, root } = await view();

    change(control(root, "assign_area"), false);
    change(control(root, "assign_area"), true);
    await settle(element);
    one(root, "form").dispatchEvent(new Event("submit", { cancelable: true }));
    await settle(element);

    expect(hass.connection.sentOf("settings/set")).toEqual([]);
  });

  test("a refused setting renders the error's translated message and marks its field", async () => {
    const hass = makeHass();
    hass.connection.answer("settings/set", () => {
      throw recordedError("settings/set");
    });
    const { element, root } = await view(hass);

    change(control<HTMLSelectElement>(root, "time_format"), "12h");
    await settle(element);
    one<HTMLButtonElement>(root, 'button[data-action="save"]').click();
    await settle(element);

    expect(text(one(root, "[data-error]"))).toBe("time_format must be one of: auto, 12h, 24h.");
    expect(control(root, "time_format").getAttribute("aria-invalid")).toBe("true");
    expect(control(root, "schedule_scope").getAttribute("aria-invalid")).toBe("false");
  });

  test("a failed first read offers to try again", async () => {
    const hass = makeHass();
    let calls = 0;
    hass.connection.answer("settings/get", () => {
      calls += 1;
      if (calls === 1) {
        throw { code: "not_loaded", message: "x" };
      }
      return response("settings/get");
    });
    const { element, root } = await view(hass);

    expect(text(one(root, '#settings [role="alert"]'))).toContain("Device Routines is not loaded.");
    one<HTMLButtonElement>(root, 'button[data-action="retry"]').click();
    await settle(element);
    expect(root.querySelectorAll("[data-setting]")).toHaveLength(12);
  });

  test("refreshSettings replaces an unsaved draft with the stored settings", async () => {
    const { hass, element, root } = await view();
    change(control<HTMLSelectElement>(root, "time_format"), "24h");
    await settle(element);

    hass.connection.answer("settings/get", () => ({ ...response<Json>("settings/get"), time_format: "12h" }));
    await element.refreshSettings();
    await settle(element);

    expect(control<HTMLSelectElement>(root, "time_format").value).toBe("12h");
    expect(one<HTMLButtonElement>(root, 'button[data-action="save"]').disabled).toBe(true);
  });
});

describe("maintenance", () => {
  function block(root: ShadowRoot, action: string): HTMLElement {
    return one(root, `[data-maintenance="${action}"]`);
  }

  test("offers the four actions", async () => {
    const { root } = await view();

    const actions = [...root.querySelectorAll("[data-maintenance]")].map((item) =>
      item.getAttribute("data-maintenance"),
    );
    expect(actions).toEqual([...MAINTENANCE_ACTIONS]);
    expect(text(block(root, "clean_up_now"))).toContain("Clean up now");
  });

  test("runs a dry run first, shows its report, and only then the real run", async () => {
    const { hass, element, root } = await view();

    one<HTMLButtonElement>(block(root, "clean_up_now"), 'button[data-action="preview"]').click();
    await settle(element);

    expect(hass.connection.sentOf("maintenance")).toEqual([documented("maintenance")]);
    const preview = one(block(root, "clean_up_now"), '[data-report="preview"]');
    expect(text(preview)).toContain("Items it would change: 1");
    expect(text(preview.querySelector("li"))).toBe("dev_desk_lamp");

    one<HTMLButtonElement>(preview, 'button[data-action="run"]').click();
    await settle(element);

    expect(hass.connection.sentOf("maintenance").at(-1)).toEqual({
      type: "device_routines/maintenance",
      action: "clean_up_now",
      dry_run: false,
    });
    const done = one(block(root, "clean_up_now"), '[data-report="done"]');
    expect(text(done)).toContain("Items changed: 1");
    one<HTMLButtonElement>(done, 'button[data-action="dismiss"]').click();
    await settle(element);
    expect(block(root, "clean_up_now").querySelector("[data-report]")).toBeNull();
  });

  test("each action previews itself, and a preview can be cancelled", async () => {
    const hass = makeHass();
    hass.connection.answer("maintenance", (message) => ({ action: message["action"], changed: [], would_change: [] }));
    const { element, root } = await view(hass);

    for (const action of MAINTENANCE_ACTIONS) {
      one<HTMLButtonElement>(block(root, action), 'button[data-action="preview"]').click();
      await settle(element);
      expect(text(block(root, action))).toContain("Running it would change nothing.");
    }
    expect(hass.connection.sentOf("maintenance").map(({ action, dry_run }) => [action, dry_run])).toEqual(
      MAINTENANCE_ACTIONS.map((action) => [action, true]),
    );

    one<HTMLButtonElement>(block(root, "rebuild_index"), 'button[data-action="cancel"]').click();
    await settle(element);
    expect(block(root, "rebuild_index").querySelector("[data-report]")).toBeNull();
    one<HTMLButtonElement>(block(root, "refresh_summaries"), 'button[data-action="run"]').click();
    await settle(element);
    expect(text(block(root, "refresh_summaries"))).toContain("Nothing needed a change.");
  });

  test("a failed action shows its translated message", async () => {
    const hass = makeHass();
    hass.connection.answer("maintenance", () => {
      throw {
        code: "maintenance_failed",
        message: "x",
        translation_placeholders: { action: "reinstall_blueprint", error: "disk full" },
      };
    });
    const { element, root } = await view(hass);

    one<HTMLButtonElement>(block(root, "reinstall_blueprint"), 'button[data-action="preview"]').click();
    await settle(element);

    expect(text(one(block(root, "reinstall_blueprint"), '[role="alert"]'))).toBe(
      "The maintenance action reinstall_blueprint could not finish: disk full. " +
        "Check the Home Assistant log and run it again.",
    );
  });
});

describe("Health", () => {
  test("comes from the Health sensor's state and attributes", async () => {
    const { root } = await view(makeHass({ states: { [HEALTH_ENTITY]: health() } }));

    expect(text(one(root, '[data-health="state"]'))).toBe("OK");
    expect(text(one(root, '[data-attribute="commit"]'))).toBe("abc1234");
    expect(text(one(root, '[data-attribute="blueprint_schema"]'))).toBe("2");
    expect(text(one(root, '[data-attribute="issues"]'))).toBe("None");
    expect(text(one(root, '[data-attribute="last_reconcile"]'))).toBe("None");
    expect(text(one(root, '[data-attribute="deployed_at"]'))).toBe("Mon 8:00 AM");
    expect(text(one(root, "#health dl"))).toContain("Routines loaded");
  });

  test("shows a degraded state with its issues, and a state it does not know as sent", async () => {
    const hass = makeHass({ states: { [HEALTH_ENTITY]: health("degraded", { issues: ["blueprint_modified", "x"] }) } });
    const { element, root } = await view(hass);

    expect(text(one(root, '[data-health="state"]'))).toBe("Degraded");
    expect(text(one(root, '[data-attribute="issues"]'))).toBe("blueprint_modified, x");

    hass.states[HEALTH_ENTITY] = health("unavailable");
    element.refreshHealth();
    await settle(element);
    expect(text(one(root, '[data-health="state"]'))).toBe("unavailable");
  });

  test("says so when the Health sensor is missing", async () => {
    const { root } = await view();

    expect(text(one(root, '[data-health="missing"]'))).toBe("The Health sensor of Device Routines is not available.");
  });
});
