// The Settings view (PRD 4.5 and 10.4): every global setting `settings/get` returns, each
// with an editor fitting its type, saved with `settings/set` carrying only the changed
// keys; the four maintenance actions, each previewed with a dry run whose report is shown
// before the real run; and Health, read from the Health sensor's state.

import { css, html, LitElement, nothing } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import type { GlobalSettings, HomeAssistant, MaintenanceAction, MaintenanceReport } from "../api";
import { getSettings, HEALTH_ENTITY, MAINTENANCE_ACTIONS, runMaintenance, setSettings } from "../api";
import { formatDateTime } from "../format";
import type { Key } from "../localize";
import { errorSetting, errorText, t } from "../localize";
import { shared } from "../styles";

type SettingKey = keyof GlobalSettings;
type Values = Record<string, unknown>;

/** How each setting of PRD 10.4 is edited; a key the console does not know yet is edited by its value's type. */
type Editor =
  | { kind: "choice"; choices: Record<string, Key> }
  | { kind: "boolean" }
  | { kind: "number" }
  | { kind: "entity" };

const EDITORS: Record<SettingKey, Editor> = {
  schedule_scope: {
    kind: "choice",
    choices: {
      all: "settings.choices.schedule_scope.all",
      routines: "settings.choices.schedule_scope.routines",
      none: "settings.choices.schedule_scope.none",
    },
  },
  time_format: {
    kind: "choice",
    choices: {
      auto: "settings.choices.time_format.auto",
      "12h": "settings.choices.time_format.12h",
      "24h": "settings.choices.time_format.24h",
    },
  },
  default_catch_up: { kind: "boolean" },
  default_respect_manual: { kind: "boolean" },
  default_late_start_window_min: { kind: "number" },
  cleanup_after_days: { kind: "number" },
  assign_area: { kind: "boolean" },
  on_removal: {
    kind: "choice",
    choices: { keep: "settings.choices.on_removal.keep", delete: "settings.choices.on_removal.delete" },
  },
  ai_task_entity: { kind: "entity" },
  ai_calls_per_hour: { kind: "number" },
  offer_conversions: { kind: "boolean" },
  raise_conflict_repairs: { kind: "boolean" },
};

const FIELD_KEYS: Record<SettingKey, { name: Key; description: Key }> = {
  schedule_scope: {
    name: "settings.fields.schedule_scope.name",
    description: "settings.fields.schedule_scope.description",
  },
  time_format: { name: "settings.fields.time_format.name", description: "settings.fields.time_format.description" },
  default_catch_up: {
    name: "settings.fields.default_catch_up.name",
    description: "settings.fields.default_catch_up.description",
  },
  default_respect_manual: {
    name: "settings.fields.default_respect_manual.name",
    description: "settings.fields.default_respect_manual.description",
  },
  default_late_start_window_min: {
    name: "settings.fields.default_late_start_window_min.name",
    description: "settings.fields.default_late_start_window_min.description",
  },
  cleanup_after_days: {
    name: "settings.fields.cleanup_after_days.name",
    description: "settings.fields.cleanup_after_days.description",
  },
  assign_area: { name: "settings.fields.assign_area.name", description: "settings.fields.assign_area.description" },
  on_removal: { name: "settings.fields.on_removal.name", description: "settings.fields.on_removal.description" },
  ai_task_entity: {
    name: "settings.fields.ai_task_entity.name",
    description: "settings.fields.ai_task_entity.description",
  },
  ai_calls_per_hour: {
    name: "settings.fields.ai_calls_per_hour.name",
    description: "settings.fields.ai_calls_per_hour.description",
  },
  offer_conversions: {
    name: "settings.fields.offer_conversions.name",
    description: "settings.fields.offer_conversions.description",
  },
  raise_conflict_repairs: {
    name: "settings.fields.raise_conflict_repairs.name",
    description: "settings.fields.raise_conflict_repairs.description",
  },
};

const MAINTENANCE_KEYS: Record<MaintenanceAction, { name: Key; description: Key }> = {
  rebuild_index: {
    name: "settings.maintenance.actions.rebuild_index.name",
    description: "settings.maintenance.actions.rebuild_index.description",
  },
  reinstall_blueprint: {
    name: "settings.maintenance.actions.reinstall_blueprint.name",
    description: "settings.maintenance.actions.reinstall_blueprint.description",
  },
  clean_up_now: {
    name: "settings.maintenance.actions.clean_up_now.name",
    description: "settings.maintenance.actions.clean_up_now.description",
  },
  refresh_summaries: {
    name: "settings.maintenance.actions.refresh_summaries.name",
    description: "settings.maintenance.actions.refresh_summaries.description",
  },
};

/** The Health attributes of TECH_SPEC 10.3, in its order. */
const HEALTH_KEYS: readonly [string, Key][] = [
  ["version", "health.attributes.version"],
  ["commit", "health.attributes.commit"],
  ["branch", "health.attributes.branch"],
  ["deployed_at", "health.attributes.deployed_at"],
  ["channel", "health.attributes.channel"],
  ["blueprint_schema", "health.attributes.blueprint_schema"],
  ["blueprint_status", "health.attributes.blueprint_status"],
  ["owned_count", "health.attributes.owned_count"],
  ["loaded_count", "health.attributes.loaded_count"],
  ["issues", "health.attributes.issues"],
  ["ha_version", "health.attributes.ha_version"],
  ["last_reconcile", "health.attributes.last_reconcile"],
];

const HEALTH_STATES: Record<string, Key> = {
  ok: "health.state.ok",
  degraded: "health.state.degraded",
  error: "health.state.error",
};

function editorOf(key: string, value: unknown): Editor {
  const known = (EDITORS as Partial<Record<string, Editor>>)[key];
  if (known !== undefined) {
    return known;
  }
  if (typeof value === "boolean") {
    return { kind: "boolean" };
  }
  return typeof value === "number" ? { kind: "number" } : { kind: "entity" };
}

/** Only the keys whose value the draft changed. */
export function changedKeys(original: Values, draft: Values): Values {
  const changes: Values = {};
  for (const [key, value] of Object.entries(draft)) {
    if (JSON.stringify(original[key]) !== JSON.stringify(value)) {
      changes[key] = value;
    }
  }
  return changes;
}

interface MaintenanceState {
  phase: "preview" | "done";
  report: MaintenanceReport;
}

export class DrSettingsView extends LitElement {
  static override properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    _settings: { state: true },
    _draft: { state: true },
    _error: { state: true },
    _saveError: { state: true },
    _saved: { state: true },
    _maintenance: { state: true },
    _maintenanceError: { state: true },
  };

  static override styles = [
    shared,
    css`
      form {
        display: grid;
        gap: 0 var(--ha-space-4, 16px);
        grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      }

      .wide {
        grid-column: 1 / -1;
      }

      dl {
        display: grid;
        gap: var(--ha-space-1, 4px) var(--ha-space-4, 16px);
        grid-template-columns: max-content 1fr;
        margin: 0;
      }

      dt {
        color: var(--secondary-text-color, #727272);
      }

      dd {
        margin: 0;
        overflow-wrap: anywhere;
      }

      .maintenance {
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        padding: var(--ha-space-2, 8px) 0;
      }

      .state-ok {
        color: var(--success-color, #43a047);
      }

      .state-degraded {
        color: var(--warning-color, #ffa600);
      }

      .state-error {
        color: var(--error-color, #db4437);
      }
    `,
  ];

  declare hass: HomeAssistant | undefined;
  declare narrow: boolean;
  declare _settings: Values | undefined;
  declare _draft: Values;
  declare _error: string | undefined;
  declare _saveError: { text: string; setting: string | undefined } | undefined;
  declare _saved: boolean;
  declare _maintenance: Partial<Record<MaintenanceAction, MaintenanceState>>;
  declare _maintenanceError: { action: MaintenanceAction; text: string } | undefined;

  private _started = false;

  constructor() {
    super();
    this.narrow = false;
    this._draft = {};
    this._saved = false;
    this._maintenance = {};
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("hass") && this.hass !== undefined && !this._started) {
      this._started = true;
      void this.refreshSettings();
    }
  }

  /** Read the stored settings again (`settings/get`); an unsaved draft is replaced. */
  async refreshSettings(): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    try {
      const settings: Values = { ...(await getSettings(hass)) };
      this._settings = settings;
      this._draft = { ...settings };
      this._error = undefined;
    } catch (error) {
      this._error = await errorText(hass, error);
    }
  }

  /** Draw the Health block again from the Health sensor (`health_changed`). */
  refreshHealth(): void {
    this.requestUpdate();
  }

  private _set(key: string, value: unknown): void {
    this._draft = { ...this._draft, [key]: value };
    this._saved = false;
  }

  private async _save(event: Event): Promise<void> {
    event.preventDefault();
    const hass = this.hass;
    if (hass === undefined || this._settings === undefined) {
      return;
    }
    const changes = changedKeys(this._settings, this._draft);
    if (Object.keys(changes).length === 0) {
      return;
    }
    try {
      const settings: Values = { ...(await setSettings(hass, changes as Partial<GlobalSettings>)) };
      this._settings = settings;
      this._draft = { ...settings };
      this._saveError = undefined;
      this._saved = true;
    } catch (error) {
      this._saveError = { text: await errorText(hass, error), setting: errorSetting(error) };
      this._saved = false;
    }
  }

  private async _maintain(action: MaintenanceAction, dryRun: boolean): Promise<void> {
    const hass = this.hass;
    if (hass === undefined) {
      return;
    }
    this._maintenanceError = undefined;
    try {
      const report = await runMaintenance(hass, action, dryRun);
      this._maintenance = { ...this._maintenance, [action]: { phase: dryRun ? "preview" : "done", report } };
    } catch (error) {
      this._maintenanceError = { action, text: await errorText(hass, error) };
    }
  }

  private _dismiss(action: MaintenanceAction): void {
    const next = { ...this._maintenance };
    delete next[action];
    this._maintenance = next;
  }

  // ------------------------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------------------------

  protected override render(): TemplateResult {
    return html`${this._renderSettings()} ${this._renderMaintenance()} ${this._renderHealth()}`;
  }

  private _renderSettings(): TemplateResult {
    const hass = this.hass;
    const settings = this._settings;
    const changed = settings === undefined ? 0 : Object.keys(changedKeys(settings, this._draft)).length;
    return html`<section id="settings">
      <h2>${t(hass, "settings.title")}</h2>
      <p class="hint">${t(hass, "settings.description")}</p>
      ${this._error === undefined ? nothing : html`<p class="error" role="alert">${this._error}</p>`}
      ${settings === undefined
        ? this._error === undefined
          ? html`<p class="notice">${t(hass, "common.loading")}</p>`
          : html`<button data-action="retry" @click=${() => void this.refreshSettings()}>
              ${t(hass, "common.retry")}
            </button>`
        : html`<form novalidate @submit=${(event: Event) => void this._save(event)}>
            ${Object.keys(settings).map((key) => this._renderField(key))}
            ${this._saveError === undefined
              ? nothing
              : html`<p class="error wide" role="alert" data-error>${this._saveError.text}</p>`}
            ${this._saved ? html`<p class="notice wide" role="status">${t(hass, "settings.saved")}</p>` : nothing}
            <div class="wide">
              <button class="primary" type="submit" data-action="save" ?disabled=${changed === 0}>
                ${t(hass, "common.save")}
              </button>
            </div>
          </form>`}
    </section>`;
  }

  private _renderField(key: string): TemplateResult {
    const hass = this.hass;
    const value = this._draft[key];
    const editor = editorOf(key, value);
    const labels = (FIELD_KEYS as Partial<Record<string, { name: Key; description: Key }>>)[key];
    const name = labels === undefined ? key : t(hass, labels.name);
    const description =
      labels === undefined ? nothing : html`<span class="description">${t(hass, labels.description)}</span>`;
    const invalid = this._saveError?.setting === key ? "true" : "false";
    if (editor.kind === "boolean") {
      return html`<label class="field" data-setting=${key}>
        <span class="field inline">
          <input
            type="checkbox"
            name=${key}
            aria-invalid=${invalid}
            .checked=${value === true}
            @change=${(event: Event) => this._set(key, (event.target as HTMLInputElement).checked)}
          />
          <span>${name}</span>
        </span>
        ${description}
      </label>`;
    }
    let control: TemplateResult;
    if (editor.kind === "choice") {
      control = html`<select
        name=${key}
        aria-invalid=${invalid}
        @change=${(event: Event) => this._set(key, (event.target as HTMLSelectElement).value)}
      >
        ${Object.entries(editor.choices).map(
          ([choice, label]) => html`<option value=${choice} ?selected=${choice === value}>${t(hass, label)}</option>`,
        )}
      </select>`;
    } else if (editor.kind === "number") {
      control = html`<input
        type="number"
        name=${key}
        step="1"
        inputmode="numeric"
        aria-invalid=${invalid}
        .value=${value === null || value === undefined ? "" : String(value)}
        @change=${(event: Event) => {
          const raw = (event.target as HTMLInputElement).value;
          const number = Number(raw);
          this._set(key, raw !== "" && Number.isFinite(number) ? number : raw);
        }}
      />`;
    } else {
      control = html`<input
        type="text"
        name=${key}
        aria-invalid=${invalid}
        placeholder=${t(hass, "common.none")}
        .value=${typeof value === "string" ? value : ""}
        @change=${(event: Event) => {
          const raw = (event.target as HTMLInputElement).value.trim();
          this._set(key, raw === "" ? null : raw);
        }}
      />`;
    }
    return html`<label class="field" data-setting=${key}>
      <span>${name}</span>
      ${control} ${description}
    </label>`;
  }

  private _renderMaintenance(): TemplateResult {
    const hass = this.hass;
    return html`<section id="maintenance">
      <h2>${t(hass, "settings.maintenance.title")}</h2>
      <p class="hint">${t(hass, "settings.maintenance.description")}</p>
      ${MAINTENANCE_ACTIONS.map((action) => this._renderAction(action))}
    </section>`;
  }

  private _renderAction(action: MaintenanceAction): TemplateResult {
    const hass = this.hass;
    const state = this._maintenance[action];
    const error = this._maintenanceError?.action === action ? this._maintenanceError.text : undefined;
    let body: TemplateResult | typeof nothing = nothing;
    if (state?.phase === "preview") {
      const entries = state.report.would_change;
      body = html`<div data-report="preview">
        <p>
          ${entries.length === 0
            ? t(hass, "settings.maintenance.would_change_none")
            : t(hass, "settings.maintenance.would_change", { count: entries.length })}
        </p>
        ${entries.length === 0 ? nothing : html`<ul>${entries.map((entry) => html`<li>${entry}</li>`)}</ul>`}
        <button class="primary" data-action="run" @click=${() => void this._maintain(action, false)}>
          ${t(hass, "settings.maintenance.run_now")}
        </button>
        <button data-action="cancel" @click=${() => this._dismiss(action)}>${t(hass, "common.cancel")}</button>
      </div>`;
    } else if (state?.phase === "done") {
      const entries = state.report.changed;
      body = html`<div data-report="done">
        <p role="status">
          ${entries.length === 0
            ? t(hass, "settings.maintenance.changed_none")
            : t(hass, "settings.maintenance.changed", { count: entries.length })}
        </p>
        ${entries.length === 0 ? nothing : html`<ul>${entries.map((entry) => html`<li>${entry}</li>`)}</ul>`}
        <button data-action="dismiss" @click=${() => this._dismiss(action)}>${t(hass, "common.close")}</button>
      </div>`;
    }
    return html`<div class="maintenance" data-maintenance=${action}>
      <strong>${t(hass, MAINTENANCE_KEYS[action].name)}</strong>
      <p class="hint">${t(hass, MAINTENANCE_KEYS[action].description)}</p>
      ${state === undefined
        ? html`<button data-action="preview" @click=${() => void this._maintain(action, true)}>
            ${t(hass, "settings.maintenance.preview")}
          </button>`
        : body}
      ${error === undefined ? nothing : html`<p class="error" role="alert">${error}</p>`}
    </div>`;
  }

  private _renderHealth(): TemplateResult {
    const hass = this.hass;
    const health = hass?.states[HEALTH_ENTITY];
    if (health === undefined) {
      return html`<section id="health">
        <h2>${t(hass, "health.title")}</h2>
        <p class="hint" data-health="missing">${t(hass, "health.missing")}</p>
      </section>`;
    }
    const stateKey = HEALTH_STATES[health.state];
    return html`<section id="health">
      <h2>${t(hass, "health.title")}</h2>
      <p data-health="state" class=${`state-${health.state}`}>
        ${stateKey === undefined ? health.state : t(hass, stateKey)}
      </p>
      <dl>
        ${HEALTH_KEYS.filter(([attribute]) => attribute in health.attributes).map(
          ([attribute, label]) =>
            html`<dt>${t(hass, label)}</dt>
              <dd data-attribute=${attribute}>${this._healthValue(health.attributes[attribute])}</dd>`,
        )}
      </dl>
    </section>`;
  }

  private _healthValue(value: unknown): string {
    if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) {
      return t(this.hass, "common.none");
    }
    if (Array.isArray(value)) {
      return value.map(String).join(", ");
    }
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
      return formatDateTime(this.hass, value);
    }
    return String(value);
  }
}

if (!customElements.get("dr-settings-view")) {
  customElements.define("dr-settings-view", DrSettingsView);
}

declare global {
  interface HTMLElementTagNameMap {
    "dr-settings-view": DrSettingsView;
  }
}
