// The time format rule (decision L63): the integration's Time format setting decides,
// and Automatic follows the user's Home Assistant profile.

import { describe, expect, test } from "vitest";

import type { HomeAssistant } from "../src/api";
import { formatDateTime, formatTime, hour12 } from "../src/format";
import { makeHass } from "./fake-hass";

const FIVE_PM = "2026-10-19T17:00:00-07:00";

function profile(language: string, timeFormat?: string): HomeAssistant {
  return makeHass({ language, locale: timeFormat === undefined ? { language } : { language, time_format: timeFormat } });
}

describe("the time format", () => {
  test("12 hour and 24 hour win over the user's profile", () => {
    expect(formatTime(profile("en", "24"), FIVE_PM, "12h")).toBe("5:00 PM");
    expect(formatTime(profile("en", "12"), FIVE_PM, "24h")).toBe("17:00");
    expect(formatDateTime(profile("en", "12"), FIVE_PM, "24h")).toBe("Mon 17:00");
  });

  test("Automatic, or no setting at all, follows the profile's choice", () => {
    expect(formatTime(profile("en", "12"), FIVE_PM, "auto")).toBe("5:00 PM");
    expect(formatTime(profile("en", "24"), FIVE_PM, "auto")).toBe("17:00");
    expect(formatTime(profile("en", "24"), FIVE_PM)).toBe("17:00");
  });

  test("a profile on its language's format reads as the language does", () => {
    expect(formatTime(profile("en", "language"), FIVE_PM, "auto")).toBe("5:00 PM");
    expect(formatTime(profile("de", "language"), FIVE_PM, "auto")).toBe("17:00");
    expect(formatTime(profile("de"), FIVE_PM)).toBe("17:00");
    expect(hour12(undefined)).toBeUndefined();
  });

  test("a profile on the system's format asks the browser", () => {
    const system = new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions().hour12;

    expect(hour12(profile("de", "system"), "auto")).toBe(system);
  });

  test("a value that is no instant shows as sent", () => {
    expect(formatTime(profile("en"), "soon", "24h")).toBe("soon");
  });
});
