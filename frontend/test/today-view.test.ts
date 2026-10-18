// The Today view against the recorded payloads of docs/api.md.

import { afterEach, describe, expect, test } from "vitest";

import type { DayItem, DaySchedule } from "../src/api";
import { groupByArea, type DrTodayView } from "../src/views/today-view";
import type { FakeHass } from "./fake-hass";
import { change, documented, makeHass, mount, one, response, settle, shadow, text } from "./fake-hass";

afterEach(() => {
  document.body.replaceChildren();
});

/** The recorded day, reversed, with an item in the kitchen and one in no area. */
function shuffledDay(): DaySchedule {
  const day = response<DaySchedule>("schedule/today");
  const kettle: DayItem = {
    time: "2026-10-19T06:30:00-07:00",
    device_id: "dev_kettle",
    area_id: "kitchen",
    action: "on",
    kind: "automation",
    automation: "automation.morning_kettle",
    conflict: false,
  };
  const porch: DayItem = {
    time: "2026-10-19T19:00:00-07:00",
    device_id: "dev_porch_light",
    area_id: null,
    action: null,
    kind: "routine",
    automation: "automation.routine_porch_light",
    conflict: false,
  };
  return { ...day, items: [porch, ...[...day.items].reverse(), kettle] };
}

async function view(hass: FakeHass = makeHass()): Promise<{ hass: FakeHass; element: DrTodayView; root: ShadowRoot }> {
  const element = await mount<DrTodayView>("dr-today-view", hass);
  return { hass, element, root: shadow(element) };
}

function rows(group: Element): string[][] {
  return [...group.querySelectorAll("tr[data-item]")].map((row) =>
    [...row.querySelectorAll("td")].map((cell) => text(cell)),
  );
}

describe("schedule/today", () => {
  test("asks for today and shows the items grouped by area, ordered by time", async () => {
    const hass = makeHass();
    hass.connection.answer("schedule/today", () => shuffledDay());
    const { root } = await view(hass);

    expect(hass.connection.sentOf("schedule/today")).toEqual([documented("schedule/today")]);
    const groups = [...root.querySelectorAll("[data-area]")];
    expect(groups.map((group) => text(group.querySelector("h3")))).toEqual(["Kitchen", "Living room", "No area"]);
    const living = rows(one(root, '[data-area="living_room"]'));
    expect(living.map((cells) => cells[0])).toEqual(["7:00 AM", "5:00 PM", "11:00 PM", "11:00 PM"]);
    const fan = "Living room fan";
    expect(living.map((cells) => cells[1])).toEqual(["Desk lamp", fan, fan, fan]);
    expect(living[0]?.[2]).toBe("On");
    expect(living[0]?.[3]).toBe("Automation automation.morning_lamp");
    expect(living[1]?.[3]).toBe("Routine automation.routine_living_room_fan");
    const porch = rows(one(root, '[data-area=""]'));
    expect(porch[0]?.[1]).toBe("dev_porch_light");
    expect(porch[0]?.[2]).toBe("Not known yet");
  });

  test("highlights the actions that take part in a conflict", async () => {
    const { root } = await view();

    const all = [...root.querySelectorAll("tr[data-item]")];
    const conflicts = all.filter((row) => row.hasAttribute("data-conflict"));
    expect(conflicts).toHaveLength(2);
    for (const row of conflicts) {
      expect(row.classList.contains("conflict")).toBe(true);
      expect(text(row.querySelector(".badge"))).toBe("Conflict");
    }
    expect(all.filter((row) => !row.hasAttribute("data-conflict")).map((row) => row.querySelector(".badge"))).toEqual([
      null,
      null,
    ]);
  });

  test("each row links to its device page", async () => {
    const { root } = await view();

    const links = [...root.querySelectorAll<HTMLAnchorElement>('tr[data-item] a[data-link="device"]')];
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/config/devices/device/dev_desk_lamp",
      "/config/devices/device/dev_living_room_fan",
      "/config/devices/device/dev_living_room_fan",
      "/config/devices/device/dev_living_room_fan",
    ]);
  });

  test("the date picker shows today and asks for the day it is set to", async () => {
    const { hass, element, root } = await view();
    const picker = one<HTMLInputElement>(root, 'input[type="date"]');

    expect(picker.value).toBe("2026-10-19");
    change(picker, "2026-10-20");
    await settle(element);
    expect(hass.connection.sentOf("schedule/today").at(-1)).toEqual({
      type: "device_routines/schedule/today",
      date: "2026-10-20",
    });
    expect(one<HTMLInputElement>(root, 'input[type="date"]').value).toBe("2026-10-20");

    change(one<HTMLInputElement>(root, 'input[type="date"]'), "");
    await settle(element);
    expect(hass.connection.sentOf("schedule/today").at(-1)).toEqual({ type: "device_routines/schedule/today" });
  });

  test("an empty day says so, and a refusal shows its message", async () => {
    const hass = makeHass();
    hass.connection.answer("schedule/today", () => ({ date: "2026-10-19", items: [] }));
    const { element, root } = await view(hass);
    expect(text(root)).toContain("Nothing is scheduled on this day.");

    hass.connection.answer("schedule/today", () => {
      throw { code: "invalid_format", message: "Invalid date" };
    });
    await element.refresh();
    await settle(element);
    expect(text(one(root, '[role="alert"]'))).toBe("Invalid date");
  });

  test("a first read that fails shows only the error", async () => {
    const hass = makeHass();
    hass.connection.answer("schedule/today", () => {
      throw { code: "not_loaded", message: "x" };
    });
    const { root } = await view(hass);

    expect(text(one(root, '[role="alert"]'))).toContain("Device Routines is not loaded.");
    expect(root.querySelector(".notice")).toBeNull();
  });
});

describe("Build B fields", () => {
  test("names come with the items, and a server without them falls back to the registry and the id", async () => {
    const hass = makeHass();
    const day = response<DaySchedule>("schedule/today");
    const [lamp, fan] = day.items as [DayItem, DayItem];
    hass.connection.answer("schedule/today", () => ({
      ...day,
      items: [
        { ...lamp, device_name: "Reading lamp", alias: "Morning lamp" },
        { ...fan, device_name: null, alias: null },
      ],
    }));
    const { root } = await view(hass);

    const cells = rows(one(root, '[data-area="living_room"]'));
    expect(cells.map((row) => [row[1], row[3]])).toEqual([
      ["Reading lamp", "Automation Morning lamp"],
      ["Living room fan", "Routine automation.routine_living_room_fan"],
    ]);
    const source = one(root, "tr[data-item] .muted");
    expect(source.getAttribute("title")).toBe("automation.morning_lamp");
  });

  test("flags the actions Only when conditions gate, with their count", async () => {
    const hass = makeHass();
    const day = response<DaySchedule>("schedule/today");
    const [lamp, fan, late] = day.items as [DayItem, DayItem, DayItem];
    hass.connection.answer("schedule/today", () => ({
      ...day,
      items: [{ ...lamp, conditions: 0 }, { ...fan, conditions: 1 }, { ...late, conditions: 2 }],
    }));
    const { root } = await view(hass);

    const flags = [...root.querySelectorAll("tr[data-item]")].map((row) => {
      const flag = row.querySelector("[data-conditions]");
      return flag === null ? null : [flag.getAttribute("data-conditions"), text(flag)];
    });
    expect(flags).toEqual([null, ["1", "If 1 condition passes"], ["2", "If 2 conditions pass"]]);
  });

  test("time cells follow the integration's time format", async () => {
    const { element, root } = await view(makeHass({ locale: { language: "en", time_format: "12" } }));
    const times = (): string[] => [...root.querySelectorAll("td.time")].map((cell) => text(cell));
    expect(times()).toEqual(["7:00 AM", "5:00 PM", "11:00 PM", "11:00 PM"]);

    element.timeFormat = "24h";
    await settle(element);
    expect(times()).toEqual(["07:00", "17:00", "23:00", "23:00"]);
  });
});

describe("groupByArea", () => {
  test("orders areas by name with no area last and keeps an unknown area by its id", () => {
    const item = (area: string | null, time: string): DayItem => ({
      time,
      device_id: "d",
      area_id: area,
      action: "off",
      kind: "routine",
      automation: "automation.a",
      conflict: false,
    });
    const groups = groupByArea(makeHass(), [
      item(null, "2026-10-19T01:00:00-07:00"),
      item("garage", "2026-10-19T03:00:00-07:00"),
      item("living_room", "2026-10-19T02:00:00-07:00"),
      item("garage", "2026-10-19T02:00:00-07:00"),
      item(null, "2026-10-19T00:30:00-07:00"),
    ]);

    expect(groups.map((group) => [group.name, group.items.map((entry) => entry.time.slice(11, 16))])).toEqual([
      ["garage", ["02:00", "03:00"]],
      ["Living room", ["02:00"]],
      ["No area", ["00:30", "01:00"]],
    ]);
  });
});
