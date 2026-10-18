// The Routines view against the recorded payloads of docs/api.md.

import { afterEach, describe, expect, test, vi } from "vitest";

import type { ConversionOffer, RoutineView } from "../src/api";
import { errorText } from "../src/localize";
import { DrRoutinesView } from "../src/views/routines-view";
import type { FakeHass } from "./fake-hass";
import {
  change,
  DEVICES_OPT,
  documented,
  fixture,
  makeHass,
  mount,
  one,
  recordedError,
  response,
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

    expect(hass.connection.sentOf("devices/opt").at(-1)).toEqual(documented("devices/opt", DEVICES_OPT.in));
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

describe("routines of opted out devices", () => {
  test("wait in their own section, apart from the routines opted in, and can be opted in again", async () => {
    const hass = makeHass();
    const [lamp, fan] = twoRoutines() as [RoutineView, RoutineView];
    hass.connection.routines = [{ ...lamp, status: "off", opted_in: false }, { ...fan, opted_in: true }];
    const { element, root } = await view(hass);

    expect(root.querySelector(`#routines tr[data-device="${LAMP}"]`)).toBeNull();
    expect(row(root, FAN)).toBeTruthy();
    const waiting = row(root, LAMP, "#opted-out");
    expect(text(one(root, "#opted-out h2"))).toBe("Opted out devices");
    expect(text(one(waiting, '[data-cell="sentence"]'))).toBe("On at 7:00 AM");
    expect(one<HTMLAnchorElement>(waiting, 'a[data-link="automation"]').getAttribute("href")).toBe(
      "/config/automation/edit/device_routines_9a40d27e18c5",
    );
    change(one<HTMLInputElement>(root, 'input[data-select="all"]'), true);
    await settle(element);
    expect(text(one(root, "[data-selection] span"))).toBe("1 selected");

    button(waiting, "opt_in_again").click();
    await settle(element);

    expect(hass.connection.sentOf("devices/opt")).toEqual([
      { type: "device_routines/devices/opt", op: "in", device_id: [LAMP] },
    ]);
  });

  test("a server that sends no opted_in shows every routine as opted in", async () => {
    const { root } = await view();

    expect(root.querySelector("#opted-out")).toBeNull();
    expect(row(root, FAN)).toBeTruthy();
  });

  test("a refresh drops an opted out routine from the selection", async () => {
    const hass = makeHass();
    hass.connection.routines = twoRoutines();
    const { element, root } = await view(hass);
    change(one<HTMLInputElement>(root, 'input[data-select="all"]'), true);
    await settle(element);
    expect(text(one(root, "[data-selection] span"))).toBe("2 selected");

    const [lamp, fan] = twoRoutines() as [RoutineView, RoutineView];
    hass.connection.routines = [{ ...lamp, opted_in: false }, fan];
    await element.refresh();
    await settle(element);

    expect(text(one(root, "[data-selection] span"))).toBe("1 selected");
  });
});

describe("the ignored placeholders", () => {
  test("name a left out target with the placeholders the server sends", async () => {
    const hass = makeHass();
    hass.connection.answer("routines/action", () => ({
      results: [],
      ignored: [
        {
          target: "dev_hall_lamp",
          kind: "device",
          reason: "no_routine",
          placeholders: { target: "dev_hall_lamp", device: "Hall lamp" },
        },
        { target: "living_room", kind: "area", reason: "no_routine", placeholders: { target: "living_room" } },
        { target: "label_1", kind: "label", reason: "no_routine", placeholders: { target: "Night" } },
        { target: LAMP, kind: "device", reason: "no_routine" },
        { target: "dev_unknown", kind: "device", reason: "no_routine" },
      ],
    }));
    const { element, root } = await view(hass);

    button(row(root, FAN), "skip_next").click();
    await settle(element);

    const lines = [...one(root, '[role="status"]').querySelectorAll("div")].map((line) => text(line));
    expect(lines).toEqual([
      "Routines changed: 0.",
      "Hall lamp was left out: Hall lamp has no routine yet. Set a start or stop time first.",
      "Living room was left out: Living room has no routine yet. Set a start or stop time first.",
      "Night was left out: Night has no routine yet. Set a start or stop time first.",
      "Desk lamp was left out: Desk lamp has no routine yet. Set a start or stop time first.",
      "dev_unknown was left out: dev_unknown has no routine yet. Set a start or stop time first.",
    ]);
  });
});

describe("the time format", () => {
  test("times follow the integration's setting, Automatic following the user's profile", async () => {
    const { element, root } = await view(makeHass({ locale: { language: "en", time_format: "12" } }));
    expect(text(one(row(root, FAN), '[data-cell="next"]'))).toBe("On Mon 5:00 PM");

    element.timeFormat = "24h";
    await settle(element);
    expect(text(one(row(root, FAN), '[data-cell="next"]'))).toBe("On Mon 17:00");

    element.timeFormat = "auto";
    await settle(element);
    expect(text(one(row(root, FAN), '[data-cell="next"]'))).toBe("On Mon 5:00 PM");
  });
});

// --------------------------------------------------------------------------------------
// Conversion candidates (FR-M1). The payloads follow plan 6.2.5 until docs/api.md
// records `conversions/list` and `conversions/convert`; then the recorded ones are used.
// --------------------------------------------------------------------------------------

function contractOffers(): { offers: ConversionOffer[] } {
  const [fan] = routines() as [RoutineView];
  return {
    offers: [
      {
        automation_id: "1760000000001",
        automation_entity_id: "automation.desk_lamp_schedule",
        alias: "Desk lamp schedule",
        device_id: LAMP,
        device_name: "Desk lamp",
        settings: { ...fan.settings, target_entity: "light.desk_lamp", on_time: "07:00:00", off_time: "09:00:00" },
        original_sentence: "On at 7:00 AM, off at 9:00 AM",
        routine_sentence: "On from 7:00 AM to 9:00 AM",
      },
    ],
  };
}

function recordedOr<T>(command: string, fallback: () => T): T {
  return fixture[command]?.examples.find((example) => example.response !== null) === undefined
    ? fallback()
    : response<T>(command);
}

function offersAnswer(): { offers: ConversionOffer[] } {
  return recordedOr("conversions/list", contractOffers);
}

function withOffers(hass: FakeHass = makeHass()): { hass: FakeHass; offers: ConversionOffer[] } {
  const answer = offersAnswer();
  hass.connection.answer("conversions/list", () => answer);
  hass.connection.answer("conversions/convert", (message) => {
    const offer = answer.offers.find((item) => item.automation_entity_id === message["automation_entity_id"]);
    if (offer === undefined) {
      throw { code: "conversion_not_offered", message: "This automation is no longer offered." };
    }
    return recordedOr("conversions/convert", () => ({
      ...(routines()[0] as RoutineView),
      device_id: offer.device_id,
      device_name: offer.device_name,
      settings: offer.settings,
    }));
  });
  return { hass, offers: answer.offers };
}

describe("conversion candidates", () => {
  test("lists every offer with its automation, device and sentence", async () => {
    const { hass, offers } = withOffers();
    const { root } = await view(hass);

    expect(hass.connection.sentOf("conversions/list")).toEqual([{ type: "device_routines/conversions/list" }]);
    expect(text(one(root, "#conversions h2"))).toBe("Automations that can become routines");
    for (const offer of offers) {
      const entry = one(root, `tr[data-offer="${offer.automation_entity_id}"]`);
      expect(text(one(entry, 'a[data-link="automation"]'))).toBe(offer.alias);
      expect(one(entry, 'a[data-link="automation"]').getAttribute("href")).toBe(
        `/config/automation/edit/${encodeURIComponent(offer.automation_id)}`,
      );
      expect(text(one(entry, 'a[data-link="device"]'))).toBe(offer.device_name);
      expect(text(one(entry, '[data-cell="sentence"]'))).toBe(offer.original_sentence);
    }
  });

  test("Convert shows both sentences, and only the confirm sends conversions/convert", async () => {
    const { hass, offers } = withOffers();
    const [offer] = offers as [ConversionOffer];
    const { element, root } = await view(hass);
    const listed = hass.connection.sentOf("routines/list").length;

    button(one(root, `tr[data-offer="${offer.automation_entity_id}"]`), "convert").click();
    await settle(element);
    const confirm = one(root, `tr[data-confirm-offer="${offer.automation_entity_id}"]`);
    expect(text(confirm)).toContain(`${offer.alias} can become a routine on ${offer.device_name}.`);
    expect(text(one(confirm, '[data-sentence="original"]'))).toBe(`Now, as the automation ${offer.original_sentence}`);
    expect(text(one(confirm, '[data-sentence="routine"]'))).toBe(`As a routine ${offer.routine_sentence}`);
    expect(hass.connection.sentOf("conversions/convert")).toEqual([]);

    button(confirm, "confirm_convert").click();
    await settle(element);

    expect(hass.connection.sentOf("conversions/convert")).toEqual([
      { type: "device_routines/conversions/convert", automation_entity_id: offer.automation_entity_id },
    ]);
    expect(text(one(root, '[role="status"]'))).toContain(`${offer.alias} is now a routine on`);
    expect(hass.connection.sentOf("routines/list")).toHaveLength(listed + 1);
    expect(hass.connection.sentOf("conversions/list")).toHaveLength(2);
    expect(root.querySelector("tr[data-confirm-offer]")).toBeNull();
  });

  test("cancelling sends nothing, and a refused conversion shows its message", async () => {
    const { hass, offers } = withOffers();
    const [offer] = offers as [ConversionOffer];
    const { element, root } = await view(hass);
    const entry = (): HTMLElement => one(root, `tr[data-offer="${offer.automation_entity_id}"]`);

    button(entry(), "convert").click();
    await settle(element);
    button(root, "cancel_convert").click();
    await settle(element);
    expect(root.querySelector("tr[data-confirm-offer]")).toBeNull();
    expect(hass.connection.sentOf("conversions/convert")).toEqual([]);

    const refusal = {
      code: "device_has_routine",
      message: "Desk lamp already has a routine",
      translation_placeholders: { device: "Desk lamp" },
    };
    hass.connection.answer("conversions/convert", () => {
      throw refusal;
    });
    button(entry(), "convert").click();
    await settle(element);
    button(root, "confirm_convert").click();
    await settle(element);

    // The integration's translation once it has one, the error's own message before.
    expect(text(one(root, '[role="status"]'))).toBe(await errorText(hass, refusal));
    expect(text(one(root, '[role="status"]'))).toContain("Desk lamp");
    expect(hass.connection.sentOf("conversions/convert")).toHaveLength(1);
  });

  test("no section without offers, nor on a server without the command", async () => {
    const hass = makeHass();
    hass.connection.answer("conversions/list", () => ({ offers: [] }));
    const { root } = await view(hass);
    expect(root.querySelector("#conversions")).toBeNull();

    const { root: older } = await view(makeHass());
    expect(older.querySelector("#conversions")).toBeNull();
    expect(older.querySelector('[role="alert"]')).toBeNull();
  });

  test("a refused list shows its message in the section", async () => {
    const hass = makeHass();
    hass.connection.answer("conversions/list", () => {
      throw { code: "not_loaded", message: "x" };
    });
    const { element, root } = await view(hass);

    expect(text(one(root, '#conversions [role="alert"]'))).toContain("Device Routines is not loaded.");
    withOffers(hass);
    await element.refreshConversions();
    await settle(element);
    expect(root.querySelector('#conversions [role="alert"]')).toBeNull();
  });

  test("a subclass can still replace the section", async () => {
    class WithCandidates extends DrRoutinesView {
      protected override renderConversionCandidates() {
        const section = document.createElement("section");
        section.id = "candidates";
        return section as never;
      }
    }
    customElements.define("dr-routines-view-with-candidates", WithCandidates);

    const extended = await mount<WithCandidates>("dr-routines-view-with-candidates", makeHass());
    expect(shadow(extended).querySelector("#candidates")).not.toBeNull();
  });
});
