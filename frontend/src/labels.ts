// The translation keys of the API's enumerated values, so every key stays a literal.

import type { Days, HomeAssistant, RoutineStatus, SummaryItem, Verb, Weekday } from "./api";
import type { Key } from "./localize";
import { t } from "./localize";

export const STATUS_KEYS: Record<RoutineStatus, Key> = {
  active: "status.active",
  paused: "status.paused",
  skipping: "status.skipping",
  off: "status.off",
  detached: "status.detached",
  missing_target: "status.missing_target",
  invalid: "status.invalid",
};

export const VERB_KEYS: Record<Verb, Key> = {
  on: "verb.on",
  off: "verb.off",
  toggle: "verb.toggle",
  start: "verb.start",
  dock: "verb.dock",
  pause: "verb.pause",
  stop: "verb.stop",
  open: "verb.open",
  close: "verb.close",
  lock: "verb.lock",
  unlock: "verb.unlock",
};

export const DAYS_KEYS: Record<Days, Key> = {
  every_day: "days.every_day",
  weekdays: "days.weekdays",
  weekends: "days.weekends",
  some_days: "days.some_days",
  weekly_schedule: "days.weekly_schedule",
};

export const WEEKDAY_KEYS: Record<Weekday, Key> = {
  mon: "weekday.mon",
  tue: "weekday.tue",
  wed: "weekday.wed",
  thu: "weekday.thu",
  fri: "weekday.fri",
  sat: "weekday.sat",
  sun: "weekday.sun",
};

export const KIND_KEYS: Record<SummaryItem["kind"], Key> = {
  routine: "kind.routine",
  automation: "kind.automation",
  detached_routine: "kind.detached_routine",
};

/**
 * The text of an enumerated value; a value newer than the console (an API addition)
 * shows as sent rather than disappearing.
 */
function known<T extends string>(hass: HomeAssistant | undefined, keys: Record<T, Key>, value: T): string {
  const key: Key | undefined = (keys as Partial<Record<string, Key>>)[value];
  return key === undefined ? value : t(hass, key);
}

export function statusText(hass: HomeAssistant | undefined, status: RoutineStatus): string {
  return known(hass, STATUS_KEYS, status);
}

export function verbText(hass: HomeAssistant | undefined, verb: Verb | null): string {
  return verb === null ? t(hass, "verb.unknown") : known(hass, VERB_KEYS, verb);
}

export function kindText(hass: HomeAssistant | undefined, kind: SummaryItem["kind"]): string {
  return known(hass, KIND_KEYS, kind);
}
