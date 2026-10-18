// The Routines view (PRD 4.5): every routine with its device, area, Schedule sentence,
// status, next action and pause state; detached routines, routines of opted out devices
// and conversion candidates in their own sections; Skip next, pause until, resume, enable
// and disable per row and for a selection; links to the device page and the automation;
// opting devices in and out; inline settings edits; converting a hand written automation
// into a routine after both sentences were shown. Every control is one command of
// docs/api.md, and the service layer decides. Fields a server before Build B does not
// send (`opted_in`, the `ignored` placeholders) and its missing `conversions/list` fall
// back to what the console showed before.

import { css, html, LitElement, nothing } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import type {
  ActionResults,
  ConversionOffer,
  DeviceChoice,
  Days,
  HomeAssistant,
  IgnoredTarget,
  RoutineAction,
  RoutineSettings,
  RoutineView,
  TimeFormat,
} from "../api";
import {
  automationPath,
  convertAutomation,
  DAYS,
  devicePath,
  getRoutine,
  isApiError,
  listConversions,
  listDevices,
  listRoutines,
  optDevices,
  runAction,
  setRoutine,
  WEEKDAYS,
} from "../api";
import { areaName, deviceName, formatDateTime, timeInputValue } from "../format";
import { DAYS_KEYS, statusText, verbText, WEEKDAY_KEYS } from "../labels";
import type { Key } from "../localize";
import { errorSetting, errorText, t } from "../localize";
import { followLink } from "../navigate";
import { shared } from "../styles";

const ACTION_KEYS: Record<RoutineAction, Key> = {
  skip_next: "routines.actions.skip_next",
  pause: "routines.actions.pause",
  resume: "routines.actions.resume",
  enable: "routines.actions.enable",
  disable: "routines.actions.disable",
};

/** The settings the inline editor offers; pulse and extra conditions stay in the automation. */
type Editable =
  | "target_entity"
  | "on_time"
  | "off_time"
  | "days"
  | "day_set"
  | "schedule_entity"
  | "turn_off_after_min"
  | "turn_back_on_after_min"
  | "late_start_window_min"
  | "catch_up"
  | "respect_manual"
  | "docked_guard";

const EDITABLE: readonly Editable[] = [
  "target_entity",
  "on_time",
  "off_time",
  "days",
  "day_set",
  "schedule_entity",
  "turn_off_after_min",
  "turn_back_on_after_min",
  "late_start_window_min",
  "catch_up",
  "respect_manual",
  "docked_guard",
];

const FIELD_KEYS: Record<Editable, Key> = {
  target_entity: "routines.edit.fields.target_entity",
  on_time: "routines.edit.fields.on_time",
  off_time: "routines.edit.fields.off_time",
  days: "routines.edit.fields.days",
  day_set: "routines.edit.fields.day_set",
  schedule_entity: "routines.edit.fields.schedule_entity",
  turn_off_after_min: "routines.edit.fields.turn_off_after_min",
  turn_back_on_after_min: "routines.edit.fields.turn_back_on_after_min",
  late_start_window_min: "routines.edit.fields.late_start_window_min",
  catch_up: "routines.edit.fields.catch_up",
  respect_manual: "routines.edit.fields.respect_manual",
  docked_guard: "routines.edit.fields.docked_guard",
};

type Draft = Pick<RoutineSettings, Editable>;

interface EditError {
  text: string;
  setting: string | undefined;
}

function draftOf(settings: RoutineSettings): Draft {
  return {
    target_entity: settings.target_entity,
    on_time: settings.on_time,
    off_time: settings.off_time,
    days: settings.days,
    day_set: [...settings.day_set],
    schedule_entity: settings.schedule_entity,
    turn_off_after_min: settings.turn_off_after_min,
    turn_back_on_after_min: settings.turn_back_on_after_min,
    late_start_window_min: settings.late_start_window_min,
    catch_up: settings.catch_up,
    respect_manual: settings.respect_manual,
    docked_guard: settings.docked_guard,
  };
}

function comparable(key: Editable, value: unknown): string {
  if (key === "on_time" || key === "off_time") {
    return typeof value === "string" ? value.slice(0, 5) : "";
  }
  if (key === "day_set" && Array.isArray(value)) {
    return WEEKDAYS.filter((day) => value.includes(day)).join(",");
  }
  return JSON.stringify(value);
}

/** Only the settings the draft changed, in the forms docs/api.md accepts. */
export function changedSettings(original: RoutineSettings, draft: Draft): Partial<Record<Editable, unknown>> {
  const changes: Partial<Record<Editable, unknown>> = {};
  for (const key of EDITABLE) {
    if (comparable(key, original[key]) !== comparable(key, draft[key])) {
      changes[key] = key === "day_set" ? WEEKDAYS.filter((day) => draft.day_set.includes(day)) : draft[key];
    }
  }
  return changes;
}

function byName(a: RoutineView, b: RoutineView): number {
  return a.device_name.localeCompare(b.device_name) || a.device_id.localeCompare(b.device_id);
}

/** A routine whose device was opted out and that waits for cleanup; absent means opted in. */
function optedOut(routine: RoutineView): boolean {
  return routine.opted_in === false;
}

/** The core's answer to a command it does not know: a server without conversion offers. */
const UNKNOWN_COMMAND = "unknown_command";

export class DrRoutinesView extends LitElement {
  static override properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    timeFormat: { attribute: false },
    _routines: { state: true },
    _error: { state: true },
    _notice: { state: true },
    _selected: { state: true },
    _pauseRow: { state: true },
    _pauseSelection: { state: true },
    _pauseUntil: { state: true },
    _editing: { state: true },
    _draft: { state: true },
    _editError: { state: true },
    _confirmOptOut: { state: true },
    _devices: { state: true },
    _suggested: { state: true },
    _devicesSelected: { state: true },
    _offers: { state: true },
    _offersError: { state: true },
    _confirmConvert: { state: true },
  };

  static override styles = [
    shared,
    css`
      .toolbar {
        align-items: center;
        display: flex;
        flex-wrap: wrap;
        gap: var(--ha-space-2, 8px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .editor form {
        display: grid;
        gap: 0 var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      }

      .editor .wide {
        grid-column: 1 / -1;
      }

      fieldset {
        border: 1px solid var(--divider-color, #e0e0e0);
        border-radius: var(--ha-border-radius-sm, 4px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .sentences {
        display: grid;
        gap: var(--ha-space-2, 8px) var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        margin: 0 0 var(--ha-space-3, 12px);
      }

      .sentences strong {
        display: block;
        font-weight: var(--ha-font-weight-medium, 500);
      }
    `,
  ];

  declare hass: HomeAssistant | undefined;
  declare narrow: boolean;
  declare timeFormat: TimeFormat | undefined;
  declare _routines: RoutineView[] | undefined;
  declare _error: string | undefined;
  declare _notice: string[];
  declare _selected: ReadonlySet<string>;
  declare _pauseRow: string | undefined;
  declare _pauseSelection: boolean;
  declare _pauseUntil: string;
  declare _editing: string | undefined;
  declare _draft: Draft | undefined;
  declare _editError: EditError | undefined;
  declare _confirmOptOut: string | undefined;
  declare _devices: DeviceChoice[] | undefined;
  declare _suggested: ReadonlySet<string>;
  declare _devicesSelected: ReadonlySet<string>;
  /** The conversion offers; undefined while unknown or on a server that has none. */
  declare _offers: ConversionOffer[] | undefined;
  declare _offersError: string | undefined;
  declare _confirmConvert: string | undefined;

  private _started = false;

  constructor() {
    super();
    this.narrow = false;
    this._notice = [];
    this._selected = new Set();
    this._pauseSelection = false;
    this._pauseUntil = "";
    this._suggested = new Set();
    this._devicesSelected = new Set();
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.hass !== undefined && !this._started) {
      this._started = true;
      void this.refresh();
    }
  }

  /** Read every routine again (`routines/list`), and the conversion offers. */
  async refresh(): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    const offers = this.refreshConversions();
    try {
      this._routines = await listRoutines(hass);
      this._error = undefined;
      const known = new Set(this._routines.filter((routine) => !optedOut(routine)).map((routine) => routine.device_id));
      this._selected = new Set([...this._selected].filter((id) => known.has(id)));
    } catch (error) {
      this._error = await errorText(hass, error);
    }
    await offers;
  }

  /** Read the conversion offers again (`conversions/list`); they change with the schedule. */
  async refreshConversions(): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    try {
      this._offers = await listConversions(hass);
      this._offersError = undefined;
    } catch (error) {
      this._offers = undefined;
      this._offersError =
        isApiError(error) && error.code === UNKNOWN_COMMAND ? undefined : await errorText(hass, error);
    }
  }

  /** Read one routine again (`routines/get`) after a `routine_changed` event. */
  async refreshRoutine(deviceId: string): Promise<void> {
    const hass = this.hass;
    if (hass === undefined || this._routines === undefined) {
      return;
    }
    try {
      const view = await getRoutine(hass, deviceId);
      const others = this._routines.filter((routine) => routine.device_id !== deviceId);
      this._routines = [...others, view].sort(byName);
    } catch (error) {
      if (isApiError(error) && error.code === "not_opted_in") {
        this._routines = this._routines.filter((routine) => routine.device_id !== deviceId);
      } else {
        this._error = await errorText(hass, error);
      }
    }
  }

  // ------------------------------------------------------------------------------------
  // Commands
  // ------------------------------------------------------------------------------------

  private _name(deviceId: string): string {
    return (
      this._routines?.find((routine) => routine.device_id === deviceId)?.device_name ??
      this._devices?.find((device) => device.device_id === deviceId)?.name ??
      deviceName(this.hass, deviceId)
    );
  }

  /**
   * The name of a target an action left out: the device the server names, else the name
   * the console knows, else the server's `target`, else the target as sent.
   */
  private _ignoredName(ignored: IgnoredTarget): string {
    const placeholders = ignored.placeholders ?? {};
    let known: string | undefined;
    if (ignored.kind === "area") {
      known = this.hass?.areas?.[ignored.target]?.name;
    } else if (ignored.kind === "device") {
      const name = this._name(ignored.target);
      known = name === ignored.target ? undefined : name;
    }
    return placeholders["device"] ?? known ?? placeholders["target"] ?? ignored.target;
  }

  private async _act(action: RoutineAction, deviceIds: string | string[], until?: string): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    let answer: ActionResults;
    try {
      answer = await runAction(hass, action, { device_id: deviceIds }, until);
    } catch (error) {
      this._notice = [await errorText(hass, error)];
      return;
    }
    this._pauseRow = undefined;
    this._pauseSelection = false;
    const lines = [t(hass, "routines.result", { count: answer.results.length })];
    for (const ignored of answer.ignored) {
      const placeholders = ignored.placeholders ?? {};
      const name = this._ignoredName(ignored);
      const reason = await errorText(hass, {
        code: ignored.reason,
        message: ignored.reason,
        translation_placeholders: { device: name, target: name, ...placeholders },
      });
      lines.push(t(hass, "routines.ignored", { target: name, reason }));
    }
    this._notice = lines;
    await this.refresh();
  }

  private _actSelection(action: RoutineAction): void {
    if (action === "pause") {
      this._pauseSelection = true;
      this._pauseRow = undefined;
      return;
    }
    void this._act(action, [...this._selected]);
  }

  private _actRow(action: RoutineAction, deviceId: string): void {
    if (action === "pause") {
      this._pauseRow = deviceId;
      this._pauseSelection = false;
      return;
    }
    void this._act(action, deviceId);
  }

  private _confirmPause(target: string | string[]): void {
    if (this._pauseUntil !== "") {
      void this._act("pause", target, this._pauseUntil);
    }
  }

  private async _optOut(deviceId: string): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    this._confirmOptOut = undefined;
    try {
      await optDevices(hass, "out", [deviceId]);
      this._notice = [t(hass, "routines.opted_out", { device: this._name(deviceId) })];
    } catch (error) {
      this._notice = [await errorText(hass, error)];
    }
    await this.refresh();
  }

  private async _optIn(deviceIds: string[]): Promise<void> {
    const hass = this.hass;
    if (hass === undefined || deviceIds.length === 0) {
      return;
    }
    try {
      const results = await optDevices(hass, "in", deviceIds);
      this._notice = [t(hass, "routines.devices.opted_in", { count: results.length })];
      this._devicesSelected = new Set();
    } catch (error) {
      this._notice = [await errorText(hass, error)];
    }
    await this.refresh();
  }

  private async _loadDevices(): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    try {
      const [eligible, suggested] = await Promise.all([listDevices(hass, "list"), listDevices(hass, "suggest")]);
      this._suggested = new Set(suggested.map((device) => device.device_id));
      const isSuggested = (device: DeviceChoice): number => (this._suggested.has(device.device_id) ? 0 : 1);
      this._devices = [...eligible].sort((a, b) => isSuggested(a) - isSuggested(b));
    } catch (error) {
      this._notice = [await errorText(hass, error)];
    }
  }

  private async _convert(offer: ConversionOffer): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    this._confirmConvert = undefined;
    try {
      const view = await convertAutomation(hass, offer.automation_entity_id);
      this._notice = [t(hass, "routines.conversions.converted", { alias: offer.alias, device: view.device_name })];
    } catch (error) {
      this._notice = [await errorText(hass, error)];
    }
    await this.refresh();
  }

  private _edit(routine: RoutineView): void {
    this._editing = routine.device_id;
    this._draft = draftOf(routine.settings);
    this._editError = undefined;
    if (this._devices === undefined) {
      void this._loadDevices();
    }
  }

  private _setDraft<K extends Editable>(key: K, value: Draft[K]): void {
    if (this._draft !== undefined) {
      this._draft = { ...this._draft, [key]: value };
    }
  }

  private async _save(event: Event, routine: RoutineView): Promise<void> {
    event.preventDefault();
    const hass = this.hass;
    if (hass === undefined || this._draft === undefined) {
      return;
    }
    const changes = changedSettings(routine.settings, this._draft);
    if (Object.keys(changes).length === 0) {
      this._editing = undefined;
      return;
    }
    try {
      const view = await setRoutine(hass, routine.device_id, changes);
      this._routines = (this._routines ?? []).map((item) => (item.device_id === view.device_id ? view : item));
      this._editing = undefined;
      this._editError = undefined;
      this._notice = [t(hass, "routines.edit.saved", { device: routine.device_name })];
    } catch (error) {
      this._editError = { text: await errorText(hass, error), setting: errorSetting(error) };
    }
  }

  // ------------------------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------------------------

  protected override render(): TemplateResult {
    const hass = this.hass;
    if (this._routines === undefined) {
      return html`<section>
        ${this._error === undefined
          ? html`<p class="notice">${t(hass, "common.loading")}</p>`
          : html`<p class="error" role="alert">${this._error}</p>
              <button data-action="retry" @click=${() => void this.refresh()}>${t(hass, "common.retry")}</button>`}
      </section>`;
    }
    const detached = this._routines.filter((routine) => routine.status === "detached");
    const optedOutRoutines = this._routines.filter((routine) => routine.status !== "detached" && optedOut(routine));
    const managed = this._routines.filter((routine) => routine.status !== "detached" && !optedOut(routine));
    return html`
      <section id="routines">
        <h2>${t(hass, "routines.title")}</h2>
        ${this._error === undefined ? nothing : html`<p class="error" role="alert">${this._error}</p>`}
        ${this._notice.length === 0
          ? nothing
          : html`<div class="notice" role="status">${this._notice.map((line) => html`<div>${line}</div>`)}</div>`}
        ${this._renderSelectionBar(managed)}
        ${managed.length === 0
          ? html`<p class="hint">${t(hass, "routines.empty")}</p>`
          : html`<div class="scroll">
              <table>
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        data-select="all"
                        aria-label=${t(hass, "routines.select_all")}
                        .checked=${managed.every((routine) => this._selected.has(routine.device_id))}
                        @change=${(event: Event) => this._selectAll(managed, event)}
                      />
                    </th>
                    <th>${t(hass, "routines.columns.device")}</th>
                    <th>${t(hass, "routines.columns.area")}</th>
                    <th>${t(hass, "routines.columns.schedule")}</th>
                    <th>${t(hass, "routines.columns.status")}</th>
                    <th>${t(hass, "routines.columns.next_action")}</th>
                    <th>${t(hass, "routines.columns.pause")}</th>
                    <th>${t(hass, "routines.columns.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  ${managed.map((routine) => this._renderRow(routine))}
                </tbody>
              </table>
            </div>`}
      </section>
      ${optedOutRoutines.length === 0 ? nothing : this._renderOptedOut(optedOutRoutines)}
      ${detached.length === 0 ? nothing : this._renderDetached(detached)}
      ${this.renderConversionCandidates()}
      ${this._renderDevices()}
    `;
  }

  /**
   * The conversion candidates section of PRD 4.5: every hand written automation that
   * does exactly what a routine does (FR-M1, `conversions/list`). Converting shows the
   * automation's sentence and the routine's side by side before anything changes. The
   * section is absent while there is no offer, and on a server without the command.
   */
  protected renderConversionCandidates(): TemplateResult | typeof nothing {
    const hass = this.hass;
    const offers = this._offers ?? [];
    if (offers.length === 0) {
      return this._offersError === undefined
        ? nothing
        : html`<section id="conversions">
            <h2>${t(hass, "routines.conversions.title")}</h2>
            <p class="error" role="alert">${this._offersError}</p>
          </section>`;
    }
    return html`<section id="conversions">
      <h2>${t(hass, "routines.conversions.title")}</h2>
      <p class="hint">${t(hass, "routines.conversions.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${t(hass, "routines.conversions.automation")}</th>
              <th>${t(hass, "routines.columns.device")}</th>
              <th>${t(hass, "routines.columns.schedule")}</th>
              <th>${t(hass, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${offers.map((offer) => this._renderOffer(offer))}
          </tbody>
        </table>
      </div>
    </section>`;
  }

  private _renderOffer(offer: ConversionOffer): TemplateResult {
    const hass = this.hass;
    const id = offer.automation_entity_id;
    const confirming = this._confirmConvert === id;
    return html`<tr data-offer=${id}>
        <td>
          <a data-link="automation" href=${automationPath(offer.automation_id)} @click=${followLink}
            >${offer.alias}</a
          >
        </td>
        <td>
          <a data-link="device" href=${devicePath(offer.device_id)} @click=${followLink}>${offer.device_name}</a>
        </td>
        <td data-cell="sentence">${offer.original_sentence}</td>
        <td>
          ${confirming
            ? nothing
            : html`<button data-action="convert" @click=${() => (this._confirmConvert = id)}>
                ${t(hass, "routines.conversions.convert")}
              </button>`}
        </td>
      </tr>
      ${confirming
        ? html`<tr data-confirm-offer=${id}>
            <td colspan="4">
              <p>${t(hass, "routines.conversions.confirm", { alias: offer.alias, device: offer.device_name })}</p>
              <div class="sentences">
                <div data-sentence="original">
                  <strong>${t(hass, "routines.conversions.original")}</strong>
                  ${offer.original_sentence}
                </div>
                <div data-sentence="routine">
                  <strong>${t(hass, "routines.conversions.routine")}</strong>
                  ${offer.routine_sentence}
                </div>
              </div>
              <button class="primary" data-action="confirm_convert" @click=${() => void this._convert(offer)}>
                ${t(hass, "routines.conversions.confirm_convert")}
              </button>
              <button data-action="cancel_convert" @click=${() => (this._confirmConvert = undefined)}>
                ${t(hass, "common.cancel")}
              </button>
            </td>
          </tr>`
        : nothing}`;
  }

  private _renderOptedOut(routines: RoutineView[]): TemplateResult {
    const hass = this.hass;
    return html`<section id="opted-out">
      <h2>${t(hass, "routines.opted_out_section.title")}</h2>
      <p class="hint">${t(hass, "routines.opted_out_section.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${t(hass, "routines.columns.device")}</th>
              <th>${t(hass, "routines.columns.area")}</th>
              <th>${t(hass, "routines.columns.schedule")}</th>
              <th>${t(hass, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${routines.map(
              (routine) => html`<tr data-device=${routine.device_id}>
                <td>
                  <a data-link="device" href=${devicePath(routine.device_id)} @click=${followLink}
                    >${routine.device_name}</a
                  >
                </td>
                <td>${areaName(hass, routine.area_id)}</td>
                <td data-cell="sentence">${routine.sentence ?? t(hass, "routines.no_sentence")}</td>
                <td>
                  <button data-action="opt_in_again" @click=${() => void this._optIn([routine.device_id])}>
                    ${t(hass, "routines.opted_out_section.opt_in_again")}
                  </button>
                  <a data-link="automation" href=${automationPath(routine.automation_id)} @click=${followLink}>
                    ${t(hass, "routines.open_automation")}
                  </a>
                </td>
              </tr>`,
            )}
          </tbody>
        </table>
      </div>
    </section>`;
  }

  private _selectAll(routines: RoutineView[], event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    this._selected = new Set(checked ? routines.map((routine) => routine.device_id) : []);
  }

  private _select(deviceId: string, event: Event): void {
    const next = new Set(this._selected);
    if ((event.target as HTMLInputElement).checked) {
      next.add(deviceId);
    } else {
      next.delete(deviceId);
    }
    this._selected = next;
  }

  private _renderSelectionBar(routines: RoutineView[]): TemplateResult | typeof nothing {
    const hass = this.hass;
    const count = routines.filter((routine) => this._selected.has(routine.device_id)).length;
    if (count === 0) {
      return nothing;
    }
    const actions: RoutineAction[] = ["skip_next", "pause", "resume", "enable", "disable"];
    return html`<div class="toolbar" data-selection>
      <span>${t(hass, "routines.selection", { count })}</span>
      ${actions.map(
        (action) =>
          html`<button data-action=${action} @click=${() => this._actSelection(action)}>
            ${t(hass, ACTION_KEYS[action])}
          </button>`,
      )}
      ${this._pauseSelection ? this._renderPauseInput([...this._selected]) : nothing}
    </div>`;
  }

  private _renderPauseInput(target: string | string[]): TemplateResult {
    const hass = this.hass;
    return html`<span class="field inline" data-pause>
      <label>
        ${t(hass, "routines.pause_until")}
        <input
          type="datetime-local"
          name="until"
          .value=${this._pauseUntil}
          @input=${(event: Event) => (this._pauseUntil = (event.target as HTMLInputElement).value)}
        />
      </label>
      <button
        class="primary"
        data-action="confirm_pause"
        ?disabled=${this._pauseUntil === ""}
        @click=${() => this._confirmPause(target)}
      >
        ${t(hass, "routines.pause_confirm")}
      </button>
      <button
        data-action="cancel_pause"
        @click=${() => {
          this._pauseRow = undefined;
          this._pauseSelection = false;
        }}
      >
        ${t(hass, "common.cancel")}
      </button>
    </span>`;
  }

  private _renderNextAction(routine: RoutineView): string {
    const hass = this.hass;
    const next = routine.next_action;
    if (next === null) {
      return t(hass, "routines.no_next_action");
    }
    return t(hass, "routines.next_action", {
      verb: verbText(hass, next.verb),
      time: formatDateTime(hass, next.at, this.timeFormat),
    });
  }

  private _renderRow(routine: RoutineView): TemplateResult {
    const hass = this.hass;
    const id = routine.device_id;
    const paused = routine.paused_until !== null;
    return html`
      <tr data-device=${id}>
        <td>
          <input
            type="checkbox"
            data-select=${id}
            aria-label=${t(hass, "routines.select_row", { device: routine.device_name })}
            .checked=${this._selected.has(id)}
            @change=${(event: Event) => this._select(id, event)}
          />
        </td>
        <td><a data-link="device" href=${devicePath(id)} @click=${followLink}>${routine.device_name}</a></td>
        <td>${areaName(hass, routine.area_id)}</td>
        <td data-cell="sentence">${routine.sentence ?? t(hass, "routines.no_sentence")}</td>
        <td data-cell="status">${statusText(hass, routine.status)}</td>
        <td data-cell="next">${this._renderNextAction(routine)}</td>
        <td data-cell="pause">
          ${paused
            ? t(hass, "routines.paused_until_time", {
                time: formatDateTime(hass, routine.paused_until ?? "", this.timeFormat),
              })
            : t(hass, "routines.not_paused")}
        </td>
        <td>
          <button data-action="skip_next" @click=${() => this._actRow("skip_next", id)}>
            ${t(hass, "routines.actions.skip_next")}
          </button>
          <button data-action="pause" @click=${() => this._actRow("pause", id)}>
            ${t(hass, "routines.actions.pause")}
          </button>
          ${paused
            ? html`<button data-action="resume" @click=${() => this._actRow("resume", id)}>
                ${t(hass, "routines.actions.resume")}
              </button>`
            : nothing}
          ${routine.enabled
            ? html`<button data-action="disable" @click=${() => this._actRow("disable", id)}>
                ${t(hass, "routines.actions.disable")}
              </button>`
            : html`<button data-action="enable" @click=${() => this._actRow("enable", id)}>
                ${t(hass, "routines.actions.enable")}
              </button>`}
          <button data-action="edit" @click=${() => this._edit(routine)}>${t(hass, "routines.actions.edit")}</button>
          ${this._confirmOptOut === id
            ? html`<button class="primary" data-action="confirm_opt_out" @click=${() => void this._optOut(id)}>
                  ${t(hass, "routines.actions.confirm_opt_out")}
                </button>
                <button data-action="cancel_opt_out" @click=${() => (this._confirmOptOut = undefined)}>
                  ${t(hass, "common.cancel")}
                </button>`
            : html`<button data-action="opt_out" @click=${() => (this._confirmOptOut = id)}>
                ${t(hass, "routines.actions.opt_out")}
              </button>`}
          <a data-link="automation" href=${automationPath(routine.automation_id)} @click=${followLink}>
            ${t(hass, "routines.open_automation")}
          </a>
        </td>
      </tr>
      ${this._pauseRow === id
        ? html`<tr data-pause-row=${id}>
            <td colspan="8">${this._renderPauseInput(id)}</td>
          </tr>`
        : nothing}
      ${this._editing === id && this._draft !== undefined
        ? html`<tr class="editor" data-editor=${id}>
            <td colspan="8">${this._renderEditor(routine, this._draft)}</td>
          </tr>`
        : nothing}
    `;
  }

  private _invalid(key: Editable): "true" | "false" {
    return this._editError?.setting === key ? "true" : "false";
  }

  private _label(key: Editable): string {
    return t(this.hass, FIELD_KEYS[key]);
  }

  private _renderEditor(routine: RoutineView, draft: Draft): TemplateResult {
    const hass = this.hass;
    const targets = this._devices?.find((device) => device.device_id === routine.device_id)?.targets ?? [];
    const choices = targets.includes(draft.target_entity) ? targets : [draft.target_entity, ...targets];
    const number = (key: "turn_off_after_min" | "turn_back_on_after_min" | "late_start_window_min") =>
      html`<label class="field">
        <span>${this._label(key)}</span>
        <input
          type="number"
          name=${key}
          step="1"
          inputmode="numeric"
          aria-invalid=${this._invalid(key)}
          .value=${String(draft[key])}
          @change=${(event: Event) => {
            const raw = (event.target as HTMLInputElement).value;
            const value = Number(raw);
            this._setDraft(key, raw !== "" && Number.isInteger(value) ? value : (raw as unknown as number));
          }}
        />
      </label>`;
    const time = (key: "on_time" | "off_time") =>
      html`<label class="field">
        <span>${this._label(key)}</span>
        <input
          type="time"
          name=${key}
          aria-invalid=${this._invalid(key)}
          .value=${timeInputValue(draft[key])}
          @change=${(event: Event) => {
            const value = (event.target as HTMLInputElement).value;
            this._setDraft(key, value === "" ? null : value);
          }}
        />
      </label>`;
    const toggle = (key: "catch_up" | "respect_manual" | "docked_guard") =>
      html`<label class="field inline">
        <input
          type="checkbox"
          name=${key}
          aria-invalid=${this._invalid(key)}
          .checked=${draft[key]}
          @change=${(event: Event) => this._setDraft(key, (event.target as HTMLInputElement).checked)}
        />
        <span>${this._label(key)}</span>
      </label>`;
    return html`<form novalidate @submit=${(event: Event) => void this._save(event, routine)}>
      <h2 class="wide">${t(hass, "routines.edit.title", { device: routine.device_name })}</h2>
      <label class="field">
        <span>${this._label("target_entity")}</span>
        <select
          name="target_entity"
          aria-invalid=${this._invalid("target_entity")}
          @change=${(event: Event) => this._setDraft("target_entity", (event.target as HTMLSelectElement).value)}
        >
          ${choices.map(
            (entity) => html`<option value=${entity} ?selected=${entity === draft.target_entity}>${entity}</option>`,
          )}
        </select>
      </label>
      ${time("on_time")} ${time("off_time")}
      <label class="field">
        <span>${this._label("days")}</span>
        <select
          name="days"
          aria-invalid=${this._invalid("days")}
          @change=${(event: Event) => this._setDraft("days", (event.target as HTMLSelectElement).value as Days)}
        >
          ${DAYS.map(
            (days) => html`<option value=${days} ?selected=${days === draft.days}>${t(hass, DAYS_KEYS[days])}</option>`,
          )}
        </select>
      </label>
      ${draft.days === "some_days"
        ? html`<fieldset class="wide" name="day_set" aria-invalid=${this._invalid("day_set")}>
            <legend>${this._label("day_set")}</legend>
            ${WEEKDAYS.map(
              (day) => html`<label class="field inline">
                <input
                  type="checkbox"
                  name="day_set"
                  value=${day}
                  .checked=${draft.day_set.includes(day)}
                  @change=${(event: Event) => {
                    const checked = (event.target as HTMLInputElement).checked;
                    const rest = (this._draft?.day_set ?? []).filter((item) => item !== day);
                    this._setDraft("day_set", checked ? [...rest, day] : rest);
                  }}
                />
                <span>${t(hass, WEEKDAY_KEYS[day])}</span>
              </label>`,
            )}
          </fieldset>`
        : nothing}
      ${draft.days === "weekly_schedule"
        ? html`<label class="field">
            <span>${this._label("schedule_entity")}</span>
            <input
              type="text"
              name="schedule_entity"
              aria-invalid=${this._invalid("schedule_entity")}
              .value=${draft.schedule_entity ?? ""}
              @change=${(event: Event) => {
                const value = (event.target as HTMLInputElement).value.trim();
                this._setDraft("schedule_entity", value === "" ? null : value);
              }}
            />
          </label>`
        : nothing}
      ${number("turn_off_after_min")} ${number("turn_back_on_after_min")} ${number("late_start_window_min")}
      ${toggle("catch_up")} ${toggle("respect_manual")} ${toggle("docked_guard")}
      ${this._editError === undefined
        ? nothing
        : html`<p class="error wide" role="alert" data-error>${this._editError.text}</p>`}
      <div class="wide">
        <button class="primary" type="submit" data-action="save">${t(hass, "common.save")}</button>
        <button type="button" data-action="cancel_edit" @click=${() => (this._editing = undefined)}>
          ${t(hass, "common.cancel")}
        </button>
      </div>
    </form>`;
  }

  private _renderDetached(routines: RoutineView[]): TemplateResult {
    const hass = this.hass;
    return html`<section id="detached">
      <h2>${t(hass, "routines.detached.title")}</h2>
      <p class="hint">${t(hass, "routines.detached.description")}</p>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${t(hass, "routines.columns.device")}</th>
              <th>${t(hass, "routines.columns.area")}</th>
              <th>${t(hass, "routines.columns.schedule")}</th>
              <th>${t(hass, "routines.columns.actions")}</th>
            </tr>
          </thead>
          <tbody>
            ${routines.map(
              (routine) => html`<tr data-device=${routine.device_id}>
                <td>
                  <a data-link="device" href=${devicePath(routine.device_id)} @click=${followLink}
                    >${routine.device_name}</a
                  >
                </td>
                <td>${areaName(hass, routine.area_id)}</td>
                <td data-cell="sentence">${routine.sentence ?? t(hass, "routines.no_sentence")}</td>
                <td>
                  <a data-link="automation" href=${automationPath(routine.automation_id)} @click=${followLink}>
                    ${t(hass, "routines.open_automation")}
                  </a>
                </td>
              </tr>`,
            )}
          </tbody>
        </table>
      </div>
    </section>`;
  }

  private _renderDevices(): TemplateResult {
    const hass = this.hass;
    const devices = this._devices;
    const withRoutine = new Set((this._routines ?? []).map((routine) => routine.device_id));
    return html`<section id="devices">
      <h2>${t(hass, "routines.devices.title")}</h2>
      <p class="hint">${t(hass, "routines.devices.description")}</p>
      ${devices === undefined
        ? html`<button data-action="load_devices" @click=${() => void this._loadDevices()}>
            ${t(hass, "routines.devices.load")}
          </button>`
        : devices.length === 0
          ? html`<p class="hint">${t(hass, "routines.devices.empty")}</p>`
          : html`<div class="toolbar">
                <button
                  class="primary"
                  data-action="opt_in_selected"
                  ?disabled=${this._devicesSelected.size === 0}
                  @click=${() => void this._optIn([...this._devicesSelected])}
                >
                  ${t(hass, "routines.devices.opt_in_selected")}
                </button>
              </div>
              <div class="scroll">
                <table>
                  <thead>
                    <tr>
                      <th></th>
                      <th>${t(hass, "routines.columns.device")}</th>
                      <th>${t(hass, "routines.columns.area")}</th>
                      <th>${t(hass, "routines.devices.targets")}</th>
                      <th>${t(hass, "routines.columns.actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    ${devices.map(
                      (device) => html`<tr data-eligible=${device.device_id}>
                        <td>
                          <input
                            type="checkbox"
                            data-select=${device.device_id}
                            aria-label=${t(hass, "routines.select_row", { device: device.name })}
                            .checked=${this._devicesSelected.has(device.device_id)}
                            @change=${(event: Event) => {
                              const next = new Set(this._devicesSelected);
                              if ((event.target as HTMLInputElement).checked) {
                                next.add(device.device_id);
                              } else {
                                next.delete(device.device_id);
                              }
                              this._devicesSelected = next;
                            }}
                          />
                        </td>
                        <td>
                          <a data-link="device" href=${devicePath(device.device_id)} @click=${followLink}
                            >${device.name}</a
                          >
                          ${this._suggested.has(device.device_id)
                            ? html`<span class="badge" data-badge="suggested"
                                >${t(hass, "routines.devices.suggested")}</span
                              >`
                            : nothing}
                          ${withRoutine.has(device.device_id)
                            ? html`<span class="badge" data-badge="has_routine"
                                >${t(hass, "routines.devices.has_routine")}</span
                              >`
                            : nothing}
                        </td>
                        <td>${areaName(hass, device.area_id)}</td>
                        <td>${device.targets.join(", ")}</td>
                        <td>
                          <button data-action="opt_in" @click=${() => void this._optIn([device.device_id])}>
                            ${t(hass, "routines.devices.opt_in")}
                          </button>
                        </td>
                      </tr>`,
                    )}
                  </tbody>
                </table>
              </div>`}
    </section>`;
  }
}

if (!customElements.get("dr-routines-view")) {
  customElements.define("dr-routines-view", DrRoutinesView);
}

declare global {
  interface HTMLElementTagNameMap {
    "dr-routines-view": DrRoutinesView;
  }
}
