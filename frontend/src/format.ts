// Names and times as the console shows them.
//
// Instants arrive as ISO 8601 strings in the instance's local time (docs/api.md,
// Conventions). The console shows that wall clock time, whatever the browser's own time
// zone, in the user's language. The clock follows the integration's Time format setting,
// so the console's times read as its sentences do; Automatic follows the user's own
// Home Assistant profile (`hass.locale.time_format`), as the rest of the frontend does.

import type { HomeAssistant, TimeFormat } from "./api";
import { t } from "./localize";

const WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

function wallClock(iso: string): Date | undefined {
  const match = WALL_CLOCK.exec(iso);
  if (match === null) {
    return undefined;
  }
  const [year, month, day, hour, minute] = match.slice(1).map(Number) as [number, number, number, number, number];
  return new Date(Date.UTC(year, month - 1, day, hour, minute));
}

/** Whether the clock reads 12 hour; undefined leaves it to the language. */
export function hour12(hass: HomeAssistant | undefined, timeFormat: TimeFormat = "auto"): boolean | undefined {
  if (timeFormat !== "auto") {
    return timeFormat === "12h";
  }
  switch (hass?.locale?.time_format) {
    case "12":
      return true;
    case "24":
      return false;
    case "system":
      return new Intl.DateTimeFormat(undefined, { hour: "numeric" }).resolvedOptions().hour12;
    default:
      return undefined;
  }
}

function formatter(
  hass: HomeAssistant | undefined,
  timeFormat: TimeFormat | undefined,
  options: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const language = hass?.locale?.language ?? hass?.language ?? "en";
  const twelve = hour12(hass, timeFormat);
  return new Intl.DateTimeFormat(language, {
    ...options,
    ...(twelve === undefined ? {} : { hour12: twelve }),
    timeZone: "UTC",
  });
}

/** `17:00` of an instant, as `5:00 PM` or `17:00`. */
export function formatTime(hass: HomeAssistant | undefined, iso: string, timeFormat?: TimeFormat): string {
  const date = wallClock(iso);
  return date === undefined
    ? iso
    : formatter(hass, timeFormat, { hour: "numeric", minute: "2-digit" }).format(date);
}

/** An instant with its weekday, as `Mon 5:00 PM`. */
export function formatDateTime(hass: HomeAssistant | undefined, iso: string, timeFormat?: TimeFormat): string {
  const date = wallClock(iso);
  return date === undefined
    ? iso
    : formatter(hass, timeFormat, { weekday: "short", hour: "numeric", minute: "2-digit" }).format(date);
}

/** An area's name from `hass.areas` when present, else its id. */
export function areaName(hass: HomeAssistant | undefined, areaId: string | null): string {
  if (areaId === null) {
    return t(hass, "common.no_area");
  }
  return hass?.areas?.[areaId]?.name ?? areaId;
}

/** A device's name from `hass.devices` when present, else its id. */
export function deviceName(hass: HomeAssistant | undefined, deviceId: string): string {
  const device = hass?.devices?.[deviceId];
  return device?.name_by_user ?? device?.name ?? deviceId;
}

/** `HH:MM` of a `HH:MM:SS` setting, for a time input; empty for no time. */
export function timeInputValue(value: string | null): string {
  return value === null ? "" : value.slice(0, 5);
}
