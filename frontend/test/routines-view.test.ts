// The Routines view against the recorded payloads of docs/api.md.

import { afterEach, describe, expect, test, vi } from "vitest";

import type { RoutineView } from "../src/api";
import { DrRoutinesView } from "../src/views/routines-view";
import type { FakeHass } from "./fake-hass";
import {
  change,
  documented,
  makeHass,
  mount,
  one,
  recordedError,
  routines,
  settle,
  shadow,
  text,
} from "./fake-hass";

const FAN = "dev_living_room_fan";
const LAMP = "dev_desk_lamp";

afterEach(() => {
  document.body.replaceChildren();
});

/** The recorded fan routine and a second routine for the desk lamp, paused and turned off. */
function twoRoutines(): RoutineView[] {
  const [fan] = routines() as [RoutineView];
  const lamp: RoutineView = {
    ...structuredClone(fan),
    device_id: LAMP,
    device_name: "Desk lamp",
    automation_id: "device_routines_9a40d27e18c5",
    automation_entity_id: "automation.routine_desk_lamp",
    settings: { ...fan.settings, target_entity: "light.desk_lamp", on_time: "07:00:00", off_time: null },
    status: "paused",
    enabled: false,
    paused_until: "2026-10-19T21:00:00-07:00",
    next_action: { at: "2026-10-20T07:00:00-07:00", verb: "on" },
    sentence: "On at 7:00 AM",
  };
  return [lamp, fan];
}

interface Mounted {
  hass: FakeHass;
  element: DrRoutinesView;
  root: ShadowRoot;
}

async function view(hass: FakeHass = makeHass()): Promise<Mounted> {
  const element = await mount<DrRoutinesView>("dr-routines-view", hass);
  return { hass, element, root: shadow(element) };
}

function row(root: ShadowRoot, deviceId: string, section = "#routines"): HTMLElement {
  return one(root, `${section} tr[data-device="${deviceId}"]`);
}

function button(scope: ParentNode, action: string): HTMLButtonElement {
  return one<HTMLButtonElement>(scope, `button[data-action="${action}"]`);
}

describe("the table", () => {
  test("lists every routine with its device, area, sentence, status, next action and pause", async () => {
    const { hass, root } = await view();

    expect(hass.connection.sentOf("routines/list")).toEqual([documented("routines/list")]);
    const fan = row(root, FAN);
    const cells = [...fan.querySelectorAll("td")].map((cell) => text(cell));
    expect(cells[1]).toBe("Living room fan");
    expect(cells[2]).toBe("Living room");
    expect(cells[3]).toBe("On at 5:00 PM");
    expect(cells[4]).toBe("Active");
    expect(cells[5]).toBe("On Mon 5:00 PM");
    expect(cells[6]).toBe("Not paused");
  });

  test("shows a paused routine's end, and an area id when hass has no area registry", async () => {
    const hass = makeHass({ areas: undefined });
    hass.connection.routines = twoRoutines();
    const { root } = await view(hass);

    const lamp = row(root, LAMP);
    expect(text(one(lamp, '[data-cell="status"]'))).toBe("Paused");
    expect(text(one(lamp, '[data-cell="pause"]'))).toBe("Until Mon 9:00 PM");
    expect(text(lamp.querySelectorAll("td")[2] ?? null)).toBe("living_room");
  });

  test("lists detached routines in their own section", async () => {
    const hass = makeHass();
    const [lamp, fan] = twoRoutines() as [RoutineView, RoutineView];
    hass.connection.routines = [{ ...lamp, status: "detached" }, fan];
    const { root } = await view(hass);

    expect(root.querySelector(`#routines tr[data-device="${LAMP}"]`)).toBeNull();
    const detached = row(root, LAMP, "#detached");
    expect(text(detached)).toContain("Desk lamp");
    expect(text(one(detached, '[data-cell="sentence"]'))).toBe("On at 7:00 AM");
    expect(row(root, FAN)).toBeTruthy();
  });

  test("says so when no device has a routine", async () => {
    const hass = makeHass();
    hass.connection.routines = [];
    const { root } = await view(hass);

    expect(text(one(root, "#routines"))).toContain("No device has a routine yet");
  });

  test("renders a refusal of routines/list, the core's unauthorized error included", async () => {
    const hass = makeHass();
    hass.connection.answer("routines/list", () => {
      throw { code: "unauthorized", message: "Unauthorized" };
    });
    const { element, root } = await view(hass);

    expect(text(one(root, '[role="alert"]'))).toBe("Unauthorized");
    hass.connection.answer("routines/list", () => ({ routines: [] }));
    button(root, "retry").click();
    await settle(element);
    expect(text(one(root, "#routines"))).toContain("No device has a routine yet");
  });

  test("links to the device page and the automation", async () => {
    const { root } = await view();
    const fan = row(root, FAN);
    const device = one<HTMLAnchorElement>(fan, 'a[data-link="device"]');
    const automation = one<HTMLAnchorElement>(fan, 'a[data-link="automation"]');

    expect(device.getAttribute("href")).toBe("/config/devices/device/dev_living_room_fan");
    expect(automation.getAttribute("href")).toBe("/config/automation/edit/device_routines_5c1e0f3a9b72");

    const changed = vi.fn();
    window.addEventListener("location-changed", changed);
    automation.click();
    window.removeEventListener("location-changed", changed);
    expect(window.location.pathname).toBe("/config/automation/edit/device_routines_5c1e0f3a9b72");
    expect(changed).toHaveBeenCalledOnce();
  });

  test("a click with a modifier key leaves the link to the browser", async () => {
    const { root } = await view();
    const device = one<HTMLAnchorElement>(row(root, FAN), 'a[data-link="device"]');
    const changed = vi.fn();
    window.addEventListener("location-changed", changed);

    device.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true }));

    window.removeEventListener("location-changed", changed);
    expect(changed).not.toHaveBeenCalled();
  });
});

describe("routines/action", () => {
  test("Skip next on a row sends the documented device target and shows what was left out", async () => {
    const { hass, element, root } = await view();

    button(row(root, FAN), "skip_next").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/action")).toEqual([
      { type: "device_routines/routines/action", action: "skip_next", target: { device_id: FAN } },
    ]);
    const notice = text(one(root, '[role="status"]'));
    expect(notice).toContain("Routines changed: 1.");
    expect(notice).toContain("Desk lamp was left out: Desk lamp has no routine yet. Set a start or stop time first.");
    expect(hass.connection.sentOf("routines/list")).toHaveLength(2);
  });

  test("Pause until on a row sends the chosen end", async () => {
    const { hass, element, root } = await view();

    button(row(root, FAN), "pause").click();
    await settle(element);
    const pauseRow = one(root, `tr[data-pause-row="${FAN}"]`);
    expect(button(pauseRow, "confirm_pause").disabled).toBe(true);
    change(one<HTMLInputElement>(pauseRow, 'input[name="until"]'), "2026-10-19T22:00");
    await settle(element);
    button(pauseRow, "confirm_pause").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/action")).toEqual([
      {
        type: "device_routines/routines/action",
        action: "pause",
        target: { device_id: FAN },
        until: "2026-10-19T22:00",
      },
    ]);
    expect(root.querySelector("tr[data-pause-row]")).toBeNull();
  });

  test("a pause can be cancelled without sending anything", async () => {
    const { hass, element, root } = await view();

    button(row(root, FAN), "pause").click();
    await settle(element);
    button(root, "cancel_pause").click();
    await settle(element);

    expect(root.querySelector("tr[data-pause-row]")).toBeNull();
    expect(hass.connection.sentOf("routines/action")).toEqual([]);
  });

  test("resume, enable and disable on a row send their action", async () => {
    const hass = makeHass();
    hass.connection.routines = twoRoutines();
    const { element, root } = await view(hass);

    expect(row(root, FAN).querySelector('button[data-action="resume"]')).toBeNull();
    expect(row(root, FAN).querySelector('button[data-action="enable"]')).toBeNull();
    button(row(root, LAMP), "resume").click();
    await settle(element);
    button(row(root, LAMP), "enable").click();
    await settle(element);
    button(row(root, FAN), "disable").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/action").map(({ action, target }) => [action, target])).toEqual([
      ["resume", { device_id: LAMP }],
      ["enable", { device_id: LAMP }],
      ["disable", { device_id: FAN }],
    ]);
  });

  test("a selection sends one action with every selected device", async () => {
    const hass = makeHass();
    hass.connection.routines = twoRoutines();
    const { element, root } = await view(hass);

    expect(root.querySelector("[data-selection]")).toBeNull();
    change(one<HTMLInputElement>(root, 'input[data-select="all"]'), true);
    await settle(element);
    expect(text(one(root, "[data-selection] span"))).toBe("2 selected");

    const bar = (): HTMLElement => one(root, "[data-selection]");
    for (const action of ["skip_next", "resume", "enable", "disable"]) {
      button(bar(), action).click();
      await settle(element);
    }
    button(bar(), "pause").click();
    await settle(element);
    change(one<HTMLInputElement>(bar(), 'input[name="until"]'), "2026-10-20T08:00");
    await settle(element);
    button(bar(), "confirm_pause").click();
    await settle(element);

    const both = { device_id: [LAMP, FAN] };
    expect(hass.connection.sentOf("routines/action")).toEqual([
      { type: "device_routines/routines/action", action: "skip_next", target: both },
      { type: "device_routines/routines/action", action: "resume", target: both },
      { type: "device_routines/routines/action", action: "enable", target: both },
      { type: "device_routines/routines/action", action: "disable", target: both },
      { type: "device_routines/routines/action", action: "pause", target: both, until: "2026-10-20T08:00" },
    ]);
  });

  test("selecting one row and clearing it again hides the selection bar", async () => {
    const { element, root } = await view();

    change(one<HTMLInputElement>(row(root, FAN), `input[data-select="${FAN}"]`), true);
    await settle(element);
    expect(text(one(root, "[data-selection] span"))).toBe("1 selected");
    change(one<HTMLInputElement>(row(root, FAN), `input[data-select="${FAN}"]`), false);
    await settle(element);
    expect(root.querySelector("[data-selection]")).toBeNull();
    change(one<HTMLInputElement>(root, 'input[data-select="all"]'), true);
    change(one<HTMLInputElement>(root, 'input[data-select="all"]'), false);
    await settle(element);
    expect(root.querySelector("[data-selection]")).toBeNull();
  });

  test("a refused action shows its translated message", async () => {
    const hass = makeHass();
    hass.connection.answer("routines/action", () => {
      throw { code: "no_routine_targets", message: "untranslated" };
    });
    const { element, root } = await view(hass);

    button(row(root, FAN), "skip_next").click();
    await settle(element);

    expect(text(one(root, '[role="status"]'))).toBe("None of the chosen targets has a routine.");
  });
});

describe("devices/opt", () => {
  test("lists eligible devices with the suggested ones marked, and opts one in", async () => {
    const { hass, element, root } = await view();

    expect(hass.connection.sentOf("devices/opt")).toEqual([]);
    button(root, "load_devices").click();
    await settle(element);

    expect(hass.connection.sentOf("devices/opt").map(({ op }) => op)).toEqual(["list", "suggest"]);
    const lamp = one(root, `tr[data-eligible="${LAMP}"]`);
    expect(lamp.querySelector('[data-badge="suggested"]')).not.toBeNull();
    expect(text(lamp)).toContain("light.desk_lamp");

    button(lamp, "opt_in").click();
    await settle(element);

    expect(hass.connection.sentOf("devices/opt").at(-1)).toEqual(documented("devices/opt", 1));
    expect(text(one(root, '[role="status"]'))).toBe("Devices opted in: 1.");
  });

  test("opts the selected eligible devices in at once", async () => {
    const { hass, element, root } = await view();
    button(root, "load_devices").click();
    await settle(element);

    expect(button(root, "opt_in_selected").disabled).toBe(true);
    change(one<HTMLInputElement>(root, `tr[data-eligible="${LAMP}"] input[data-select="${LAMP}"]`), true);
    await settle(element);
    button(root, "opt_in_selected").click();
    await settle(element);

    expect(hass.connection.sentOf("devices/opt").at(-1)).toEqual({
      type: "device_routines/devices/opt",
      op: "in",
      device_id: [LAMP],
    });
  });

  test("marks an eligible device that already has a routine", async () => {
    const hass = makeHass();
    hass.connection.routines = twoRoutines();
    const { element, root } = await view(hass);
    button(root, "load_devices").click();
    await settle(element);

    expect(one(root, `tr[data-eligible="${LAMP}"]`).querySelector('[data-badge="has_routine"]')).not.toBeNull();
  });

  test("opting out asks once more, then sends devices/opt out", async () => {
    const { hass, element, root } = await view();

    button(row(root, FAN), "opt_out").click();
    await settle(element);
    button(row(root, FAN), "cancel_opt_out").click();
    await settle(element);
    expect(hass.connection.sentOf("devices/opt")).toEqual([]);

    button(row(root, FAN), "opt_out").click();
    await settle(element);
    button(row(root, FAN), "confirm_opt_out").click();
    await settle(element);

    expect(hass.connection.sentOf("devices/opt")).toEqual([
      { type: "device_routines/devices/opt", op: "out", device_id: [FAN] },
    ]);
    expect(text(one(root, '[role="status"]'))).toContain("Living room fan is opted out.");
  });

  test("a refused opt in shows its translated message", async () => {
    const hass = makeHass();
    hass.connection.answer("devices/opt", (message) => {
      if (message["op"] === "in") {
        throw { code: "not_eligible", message: "x", translation_placeholders: { device: "Desk lamp" } };
      }
      return { devices: [{ device_id: LAMP, name: "Desk lamp", area_id: null, targets: ["light.desk_lamp"] }] };
    });
    const { element, root } = await view(hass);
    button(root, "load_devices").click();
    await settle(element);

    expect(text(one(root, `tr[data-eligible="${LAMP}"]`))).toContain("No area");
    button(root, "opt_in").click();
    await settle(element);

    expect(text(one(root, '[role="status"]'))).toBe("Desk lamp has no entity a routine can control.");
  });
});

describe("routines/set", () => {
  async function openEditor(hass: FakeHass = makeHass()): Promise<Mounted & { editor: HTMLElement }> {
    const { element, root } = await view(hass);
    button(row(root, FAN), "edit").click();
    await settle(element);
    return { hass, element, root, editor: one(root, `tr[data-editor="${FAN}"]`) };
  }

  test("an inline edit sends only the changed settings", async () => {
    const { hass, element, editor } = await openEditor();

    expect(one<HTMLInputElement>(editor, 'input[name="on_time"]').value).toBe("17:00");
    expect(one<HTMLSelectElement>(editor, 'select[name="target_entity"]').value).toBe("switch.living_room_fan");
    change(one<HTMLInputElement>(editor, 'input[name="off_time"]'), "22:30");
    change(one<HTMLSelectElement>(editor, 'select[name="days"]'), "weekdays");
    await settle(element);
    button(editor, "save").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/set")).toEqual([documented("routines/set")]);
    const root = shadow(element);
    expect(root.querySelector("tr[data-editor]")).toBeNull();
    expect(text(one(root, '[role="status"]'))).toBe("The settings of Living room fan are saved.");
  });

  test("every field of the editor reaches routines/set in its documented form", async () => {
    const { hass, element, editor } = await openEditor();

    change(one<HTMLInputElement>(editor, 'input[name="on_time"]'), "");
    change(one<HTMLInputElement>(editor, 'input[name="turn_off_after_min"]'), "30");
    change(one<HTMLInputElement>(editor, 'input[name="late_start_window_min"]'), "");
    change(one<HTMLInputElement>(editor, 'input[name="catch_up"]'), false);
    change(one<HTMLInputElement>(editor, 'input[name="respect_manual"]'), false);
    change(one<HTMLInputElement>(editor, 'input[name="docked_guard"]'), false);
    change(one<HTMLSelectElement>(editor, 'select[name="days"]'), "some_days");
    await settle(element);
    change(one<HTMLInputElement>(editor, 'input[name="day_set"][value="sun"]'), false);
    change(one<HTMLInputElement>(editor, 'input[name="day_set"][value="mon"]'), false);
    await settle(element);
    change(one<HTMLInputElement>(editor, 'input[name="day_set"][value="mon"]'), true);
    await settle(element);
    button(editor, "save").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/set")[0]?.["settings"]).toEqual({
      on_time: null,
      days: "some_days",
      day_set: ["mon", "tue", "wed", "thu", "fri", "sat"],
      turn_off_after_min: 30,
      late_start_window_min: "",
      catch_up: false,
      respect_manual: false,
      docked_guard: false,
    });
  });

  test("a weekly schedule edit names its schedule entity", async () => {
    const { hass, element, editor } = await openEditor();

    change(one<HTMLSelectElement>(editor, 'select[name="days"]'), "weekly_schedule");
    await settle(element);
    change(one<HTMLInputElement>(editor, 'input[name="schedule_entity"]'), " schedule.living_room_fan ");
    change(one<HTMLInputElement>(editor, 'input[name="on_time"]'), "");
    change(one<HTMLInputElement>(editor, 'input[name="off_time"]'), "");
    await settle(element);
    button(editor, "save").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/set")[0]?.["settings"]).toEqual({
      on_time: null,
      off_time: null,
      days: "weekly_schedule",
      schedule_entity: "schedule.living_room_fan",
    });
  });

  test("a target from the eligible devices can be chosen", async () => {
    const hass = makeHass();
    hass.connection.answer("devices/opt", () => ({
      devices: [
        {
          device_id: FAN,
          name: "Living room fan",
          area_id: "living_room",
          targets: ["switch.living_room_fan", "light.fan_light"],
        },
      ],
    }));
    const { element, editor } = await openEditor(hass);

    change(one<HTMLSelectElement>(editor, 'select[name="target_entity"]'), "light.fan_light");
    await settle(element);
    button(editor, "save").click();
    await settle(element);

    expect(hass.connection.sentOf("routines/set")[0]?.["settings"]).toEqual({ target_entity: "light.fan_light" });
  });

  test("saving without a change or cancelling sends nothing", async () => {
    const { hass, element, editor } = await openEditor();

    button(editor, "save").click();
    await settle(element);
    const root = shadow(element);
    expect(root.querySelector("tr[data-editor]")).toBeNull();
    button(row(root, FAN), "edit").click();
    await settle(element);
    button(root, "cancel_edit").click();
    await settle(element);

    expect(root.querySelector("tr[data-editor]")).toBeNull();
    expect(hass.connection.sentOf("routines/set")).toEqual([]);
  });

  test("a refused edit renders the error's translated message and marks its field", async () => {
    const hass = makeHass();
    hass.connection.answer("routines/set", () => {
      throw recordedError("conventions");
    });
    const { element, editor } = await openEditor(hass);

    change(one<HTMLInputElement>(editor, 'input[name="off_time"]'), "17:00");
    await settle(element);
    button(editor, "save").click();
    await settle(element);

    const shown = one(shadow(element), `tr[data-editor="${FAN}"]`);
    expect(text(one(shown, "[data-error]"))).toBe("The start and stop times are the same. Choose two different times.");
    expect(one(shown, 'input[name="off_time"]').getAttribute("aria-invalid")).toBe("true");
    expect(one(shown, 'input[name="on_time"]').getAttribute("aria-invalid")).toBe("false");
    expect(hass.loadBackendTranslation).toHaveBeenCalledWith("exceptions", "device_routines");
  });
});

describe("refreshRoutine", () => {
  test("replaces one row from routines/get and drops a routine that is gone", async () => {
    const hass = makeHass();
    hass.connection.routines = twoRoutines();
    const { element, root } = await view(hass);

    const [lamp, fan] = twoRoutines() as [RoutineView, RoutineView];
    hass.connection.routines = [lamp, { ...fan, sentence: "On at 6:00 PM" }];
    await element.refreshRoutine(FAN);
    await settle(element);
    expect(hass.connection.sentOf("routines/get")).toEqual([
      { type: "device_routines/routines/get", device_id: FAN },
    ]);
    expect(text(one(row(root, FAN), '[data-cell="sentence"]'))).toBe("On at 6:00 PM");

    hass.connection.routines = [fan];
    await element.refreshRoutine(LAMP);
    await settle(element);
    expect(root.querySelector(`tr[data-device="${LAMP}"]`)).toBeNull();
  });

  test("shows any other refusal", async () => {
    const hass = makeHass();
    const { element, root } = await view(hass);
    hass.connection.answer("routines/get", () => {
      throw { code: "not_loaded", message: "x" };
    });

    await element.refreshRoutine(FAN);
    await settle(element);

    expect(text(one(root, '[role="alert"]'))).toContain("Device Routines is not loaded.");
  });
});

describe("the conversion candidates extension point", () => {
  test("renders nothing until its API exists, and a subclass can fill it", async () => {
    class WithCandidates extends DrRoutinesView {
      protected override renderConversionCandidates() {
        const section = document.createElement("section");
        section.id = "candidates";
        return section as never;
      }
    }
    customElements.define("dr-routines-view-with-candidates", WithCandidates);

    const { root } = await view();
    expect(root.querySelector("#candidates")).toBeNull();

    const extended = await mount<WithCandidates>("dr-routines-view-with-candidates", makeHass());
    expect(shadow(extended).querySelector("#candidates")).not.toBeNull();
  });
});
