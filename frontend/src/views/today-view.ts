// The Today view (PRD 4.5): every action planned for one local day, routines and hand
// written automations alike, grouped by area and ordered by time, with the actions that
// take part in a conflict highlighted and the ones Only when conditions gate flagged
// (FR-R9). Each row links to its device page. The day is today unless the date picker
// names another one. Names come with the items; a server without them (before Build B)
// falls back to `hass.devices` and the automation's entity id.

import { css, html, LitElement, nothing } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import type { DayItem, DaySchedule, HomeAssistant, TimeFormat } from "../api";
import { devicePath, scheduleToday } from "../api";
import { areaName, deviceName, formatTime } from "../format";
import { kindText, verbText } from "../labels";
import { errorText, t } from "../localize";
import { followLink } from "../navigate";
import { shared } from "../styles";

export interface AreaGroup {
  areaId: string | null;
  name: string;
  items: DayItem[];
}

/** The day's items by area (by area name, no area last), each area's items by time. */
export function groupByArea(hass: HomeAssistant | undefined, items: DayItem[]): AreaGroup[] {
  const groups = new Map<string | null, DayItem[]>();
  for (const item of items) {
    const list = groups.get(item.area_id) ?? [];
    list.push(item);
    groups.set(item.area_id, list);
  }
  return [...groups.entries()]
    .map(([areaId, list]) => ({
      areaId,
      name: areaName(hass, areaId),
      items: [...list].sort((a, b) => Date.parse(a.time) - Date.parse(b.time)),
    }))
    .sort((a, b) => {
      if (a.areaId === null || b.areaId === null) {
        return a.areaId === b.areaId ? 0 : a.areaId === null ? 1 : -1;
      }
      return a.name.localeCompare(b.name) || a.areaId.localeCompare(b.areaId);
    });
}

export class DrTodayView extends LitElement {
  static override properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    timeFormat: { attribute: false },
    _schedule: { state: true },
    _date: { state: true },
    _error: { state: true },
  };

  static override styles = [
    shared,
    css`
      .toolbar {
        align-items: center;
        display: flex;
        gap: var(--ha-space-2, 8px);
        margin: 0 0 var(--ha-space-3, 12px);
      }

      h3 {
        font-size: var(--ha-font-size-m, 14px);
        font-weight: var(--ha-font-weight-medium, 500);
        margin: var(--ha-space-4, 16px) 0 var(--ha-space-2, 8px);
      }

      tr.conflict td:first-child {
        border-inline-start: 4px solid var(--warning-color, #ffa600);
      }

      .badge.conflict {
        color: var(--warning-color, #ffa600);
      }

      td.time {
        white-space: nowrap;
      }
    `,
  ];

  declare hass: HomeAssistant | undefined;
  declare narrow: boolean;
  declare timeFormat: TimeFormat | undefined;
  declare _schedule: DaySchedule | undefined;
  declare _date: string | undefined;
  declare _error: string | undefined;

  private _started = false;

  constructor() {
    super();
    this.narrow = false;
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.hass !== undefined && !this._started) {
      this._started = true;
      void this.refresh();
    }
  }

  /** Read the shown day again (`schedule/today`); the first read asks for today. */
  async refresh(): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    try {
      this._schedule = await scheduleToday(hass, this._date);
      this._date = this._schedule.date;
      this._error = undefined;
    } catch (error) {
      this._error = await errorText(hass, error);
    }
  }

  private _pick(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this._date = value === "" ? undefined : value;
    void this.refresh();
  }

  protected override render(): TemplateResult {
    const hass = this.hass;
    const schedule = this._schedule;
    return html`<section>
      <h2>${t(hass, "today.title")}</h2>
      <div class="toolbar">
        <label class="field inline">
          <span>${t(hass, "today.date")}</span>
          <input type="date" name="date" .value=${this._date ?? ""} @change=${(event: Event) => this._pick(event)} />
        </label>
      </div>
      ${this._error === undefined ? nothing : html`<p class="error" role="alert">${this._error}</p>`}
      ${schedule === undefined
        ? this._error === undefined
          ? html`<p class="notice">${t(hass, "common.loading")}</p>`
          : nothing
        : schedule.items.length === 0
          ? html`<p class="hint">${t(hass, "today.empty")}</p>`
          : groupByArea(hass, schedule.items).map((group) => this._renderGroup(group))}
    </section>`;
  }

  private _renderGroup(group: AreaGroup): TemplateResult {
    const hass = this.hass;
    return html`<div data-area=${group.areaId ?? ""}>
      <h3>${group.name}</h3>
      <div class="scroll">
        <table>
          <thead>
            <tr>
              <th>${t(hass, "today.columns.time")}</th>
              <th>${t(hass, "today.columns.device")}</th>
              <th>${t(hass, "today.columns.action")}</th>
              <th>${t(hass, "today.columns.source")}</th>
            </tr>
          </thead>
          <tbody>
            ${group.items.map((item) => this._renderItem(item))}
          </tbody>
        </table>
      </div>
    </div>`;
  }

  private _renderConditions(count: number): TemplateResult | typeof nothing {
    const hass = this.hass;
    if (count <= 0) {
      return nothing;
    }
    return html`<span class="badge" data-conditions=${count}>
      ${count === 1 ? t(hass, "today.condition_one") : t(hass, "today.condition_many", { count })}
    </span>`;
  }

  private _renderItem(item: DayItem): TemplateResult {
    const hass = this.hass;
    return html`<tr class=${item.conflict ? "conflict" : ""} data-item ?data-conflict=${item.conflict}>
      <td class="time">${formatTime(hass, item.time, this.timeFormat)}</td>
      <td>
        <a data-link="device" href=${devicePath(item.device_id)} @click=${followLink}
          >${item.device_name ?? deviceName(hass, item.device_id)}</a
        >
      </td>
      <td>
        ${verbText(hass, item.action)}
        ${item.conflict ? html`<span class="badge conflict">${t(hass, "today.conflict")}</span>` : nothing}
        ${this._renderConditions(item.conditions ?? 0)}
      </td>
      <td>
        ${kindText(hass, item.kind)}
        ${item.kind === "routine"
          ? nothing
          : html`<span class="muted" title=${item.automation}>${item.alias ?? item.automation}</span>`}
      </td>
    </tr>`;
  }
}

if (!customElements.get("dr-today-view")) {
  customElements.define("dr-today-view", DrTodayView);
}

declare global {
  interface HTMLElementTagNameMap {
    "dr-today-view": DrTodayView;
  }
}
