// The console's side of docs/api.md: the payload types of its Types section and one
// function per command. Data comes only from `hass.connection` (decision L62); the
// console adds no semantics of its own (PRD 4.5, P16).

export const DOMAIN = "device_routines";
export const HEALTH_ENTITY = "sensor.device_routines_health";

// --------------------------------------------------------------------------------------
// The part of Home Assistant's frontend `hass` object the console reads
// --------------------------------------------------------------------------------------

export interface MessageBase {
  type: string;
  [key: string]: unknown;
}

export interface Connection {
  sendMessagePromise<T>(message: MessageBase): Promise<T>;
  subscribeMessage<T>(callback: (event: T) => void, message: MessageBase): Promise<() => Promise<void> | void>;
}

export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface AreaEntry {
  area_id: string;
  name: string;
}

export interface DeviceEntry {
  id: string;
  name: string | null;
  name_by_user: string | null;
}

export type LocalizeFunc = (key: string, values?: Record<string, unknown>) => string;

export interface HomeAssistant {
  connection: Connection;
  states: Record<string, HassEntity | undefined>;
  areas?: Record<string, AreaEntry | undefined>;
  devices?: Record<string, DeviceEntry | undefined>;
  language?: string;
  locale?: { language?: string; time_format?: string };
  localize: LocalizeFunc;
  loadBackendTranslation?: (category: string, integration: string) => Promise<LocalizeFunc | undefined>;
}

export interface PanelRoute {
  prefix: string;
  path: string;
}

export interface PanelInfo {
  url_path?: string;
  title?: string | null;
  config?: Record<string, unknown> | null;
}

// --------------------------------------------------------------------------------------
// Types (docs/api.md, Types)
// --------------------------------------------------------------------------------------

export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export type Days = "every_day" | "weekdays" | "weekends" | "some_days" | "weekly_schedule";
export const DAYS: readonly Days[] = ["every_day", "weekdays", "weekends", "some_days", "weekly_schedule"];

export type RoutineStatus =
  | "active"
  | "paused"
  | "skipping"
  | "off"
  | "detached"
  | "missing_target"
  | "invalid";

export type Verb =
  | "on"
  | "off"
  | "toggle"
  | "start"
  | "dock"
  | "pause"
  | "stop"
  | "open"
  | "close"
  | "lock"
  | "unlock";

/** A sun relative bound (Build B, FR-R10); the console shows nothing special for it yet. */
export type TimeKind = "time" | "sunrise" | "sunset";

export interface Pulse {
  at: string;
  minutes: number;
  min_steady_min: number;
}

export interface RoutineSettings {
  target_entity: string;
  on_time: string | null;
  off_time: string | null;
  days: Days;
  day_set: Weekday[];
  schedule_entity: string | null;
  turn_off_after_min: number;
  turn_back_on_after_min: number;
  catch_up: boolean;
  late_start_window_min: number;
  respect_manual: boolean;
  pulse: Pulse | null;
  extra_conditions: Record<string, unknown>[];
  docked_guard: boolean;
  on_kind?: TimeKind;
  on_sun_offset_min?: number;
  off_kind?: TimeKind;
  off_sun_offset_min?: number;
}

export interface Occurrence {
  at: string;
  verb: Verb | null;
}

export interface SummaryItem {
  kind: "routine" | "automation" | "detached_routine";
  automation_entity: string;
  alias: string;
  summary: string;
  next_run: string | null;
  source: "parser" | "ai" | "none";
  enabled: boolean;
  custom_logic: boolean;
  parts: string[];
}

export interface Conflict {
  a: number;
  b: number;
  reason_key: "opposite_same_minute" | "off_in_on_window" | "on_in_off_window";
  at: string | null;
}

export interface RoutineView {
  device_id: string;
  device_name: string;
  area_id: string | null;
  automation_id: string;
  automation_entity_id: string | null;
  settings: RoutineSettings;
  status: RoutineStatus;
  enabled: boolean;
  paused_until: string | null;
  skipped_action: Occurrence | null;
  next_action: Occurrence | null;
  sentence: string | null;
  items: SummaryItem[];
  conflicts: Conflict[];
  override: boolean;
  last_change_source: "automation" | "user" | "device" | null;
}

export type RoutineAction = "skip_next" | "pause" | "resume" | "enable" | "disable";

/** A native target; `"all"` is reserved for a later version and refused (D24). */
export interface Target {
  device_id?: string | string[];
  entity_id?: string | string[];
  area_id?: string | string[];
  floor_id?: string | string[];
  label_id?: string | string[];
}

export interface ActionResult {
  device_id: string;
  device_name: string;
  action: RoutineAction;
  paused_until: string | null;
  skipped_action: Occurrence | null;
  next_action: Occurrence | null;
}

export interface IgnoredTarget {
  target: string;
  kind: "device" | "entity" | "area" | "label" | "floor";
  reason: string;
}

export interface ActionResults {
  results: ActionResult[];
  ignored: IgnoredTarget[];
}

export interface DeviceChoice {
  device_id: string;
  name: string;
  area_id: string | null;
  targets: string[];
}

export interface OptResult {
  device_id: string;
  opted_in: boolean;
  changed: boolean;
  view: RoutineView | null;
}

export interface DayItem {
  time: string;
  device_id: string;
  area_id: string | null;
  action: Verb | null;
  kind: SummaryItem["kind"];
  automation: string;
  conflict: boolean;
}

export interface DaySchedule {
  date: string;
  items: DayItem[];
}

export interface GlobalSettings {
  schedule_scope: "all" | "routines" | "none";
  time_format: "auto" | "12h" | "24h";
  default_catch_up: boolean;
  default_respect_manual: boolean;
  default_late_start_window_min: number;
  cleanup_after_days: number;
  assign_area: boolean;
  on_removal: "keep" | "delete";
  ai_task_entity: string | null;
  ai_calls_per_hour: number;
  offer_conversions: boolean;
  raise_conflict_repairs: boolean;
}

export type MaintenanceAction = "clean_up_now" | "rebuild_index" | "reinstall_blueprint" | "refresh_summaries";
export const MAINTENANCE_ACTIONS: readonly MaintenanceAction[] = [
  "rebuild_index",
  "reinstall_blueprint",
  "clean_up_now",
  "refresh_summaries",
];

export interface MaintenanceReport {
  action: MaintenanceAction;
  changed: string[];
  would_change: string[];
}

export type EventKind = "routine_changed" | "schedule_changed" | "settings_changed" | "health_changed";

export interface ManagerEvent {
  kind: EventKind;
  device_id: string | null;
  reason: string | null;
  data: Record<string, unknown> | null;
}

/** A refusal (docs/api.md, Errors): `code` is the translation key, or a core code. */
export interface ApiError {
  code: string;
  message: string;
  translation_key?: string | null;
  translation_placeholders?: Record<string, string> | null;
  translation_domain?: string | null;
}

export function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { code?: unknown }).code === "string" &&
    typeof (value as { message?: unknown }).message === "string"
  );
}

// --------------------------------------------------------------------------------------
// Commands
// --------------------------------------------------------------------------------------

function send<T>(hass: HomeAssistant, command: string, fields: Record<string, unknown> = {}): Promise<T> {
  return hass.connection.sendMessagePromise<T>({ type: `${DOMAIN}/${command}`, ...fields });
}

export async function listRoutines(hass: HomeAssistant): Promise<RoutineView[]> {
  return (await send<{ routines: RoutineView[] }>(hass, "routines/list")).routines;
}

export function getRoutine(hass: HomeAssistant, deviceId: string): Promise<RoutineView> {
  return send(hass, "routines/get", { device_id: deviceId });
}

export function setRoutine(
  hass: HomeAssistant,
  deviceId: string,
  settings: Partial<Record<keyof RoutineSettings, unknown>>,
): Promise<RoutineView> {
  return send(hass, "routines/set", { device_id: deviceId, settings });
}

export function runAction(
  hass: HomeAssistant,
  action: RoutineAction,
  target: Target,
  until?: string,
): Promise<ActionResults> {
  return send(hass, "routines/action", until === undefined ? { action, target } : { action, target, until });
}

export async function listDevices(hass: HomeAssistant, op: "list" | "suggest"): Promise<DeviceChoice[]> {
  return (await send<{ devices: DeviceChoice[] }>(hass, "devices/opt", { op })).devices;
}

export async function optDevices(hass: HomeAssistant, op: "in" | "out", deviceIds: string[]): Promise<OptResult[]> {
  return (await send<{ results: OptResult[] }>(hass, "devices/opt", { op, device_id: deviceIds })).results;
}

export function scheduleToday(hass: HomeAssistant, date?: string): Promise<DaySchedule> {
  return send(hass, "schedule/today", date === undefined ? {} : { date });
}

export function getSettings(hass: HomeAssistant): Promise<GlobalSettings> {
  return send(hass, "settings/get");
}

export function setSettings(hass: HomeAssistant, settings: Partial<GlobalSettings>): Promise<GlobalSettings> {
  return send(hass, "settings/set", { settings });
}

export function runMaintenance(
  hass: HomeAssistant,
  action: MaintenanceAction,
  dryRun: boolean,
): Promise<MaintenanceReport> {
  return send(hass, "maintenance", { action, dry_run: dryRun });
}

/** Subscribe to the manager's events; the promise gives the function that ends it. */
export function subscribe(
  hass: HomeAssistant,
  callback: (event: ManagerEvent) => void,
): Promise<() => Promise<void> | void> {
  return hass.connection.subscribeMessage<ManagerEvent>(callback, { type: `${DOMAIN}/subscribe` });
}

// --------------------------------------------------------------------------------------
// Links (PRD 4.5: open the device page or the automation)
// --------------------------------------------------------------------------------------

export function devicePath(deviceId: string): string {
  return `/config/devices/device/${encodeURIComponent(deviceId)}`;
}

export function automationPath(automationId: string): string {
  return `/config/automation/edit/${encodeURIComponent(automationId)}`;
}
