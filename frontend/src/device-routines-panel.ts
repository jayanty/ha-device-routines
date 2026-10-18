// The Device Routines console: a Home Assistant custom panel (PRD 4.5, decision L62).
//
// The core gives a custom panel `hass`, `narrow`, `route` and `panel`. The panel shows
// one of three views, chosen by the path after the panel's prefix (`/today`) or the tabs,
// and holds the one `device_routines/subscribe` subscription of the console: each event
// refreshes the view it concerns when that view is open (a view reads everything again
// when it opens). The subscription ends when the panel leaves the page.

import { css, html, LitElement, nothing } from "lit";
import type { PropertyValues, TemplateResult } from "lit";

import type { HomeAssistant, ManagerEvent, PanelInfo, PanelRoute } from "./api";
import { subscribe } from "./api";
import type { Key } from "./localize";
import { t } from "./localize";
import { navigate } from "./navigate";
import { shared } from "./styles";
import "./views/routines-view";
import "./views/settings-view";
import "./views/today-view";

export type ViewName = "routines" | "today" | "settings";
export const VIEWS: readonly ViewName[] = ["routines", "today", "settings"];

const TAB_KEYS: Record<ViewName, Key> = {
  routines: "panel.tabs.routines",
  today: "panel.tabs.today",
  settings: "panel.tabs.settings",
};

// Three bars: the menu button's icon, drawn here so no icon element is needed.
const MENU_ICON = "M3 6h18v2H3zm0 5h18v2H3zm0 5h18v2H3z";

function viewOf(route: PanelRoute | undefined): ViewName | undefined {
  const segment = route?.path.split("/").find((part) => part !== "");
  return VIEWS.find((view) => view === segment);
}

type Unsubscribe = () => Promise<void> | void;

export class DeviceRoutinesPanel extends LitElement {
  static override properties = {
    hass: { attribute: false },
    narrow: { type: Boolean, reflect: true },
    route: { attribute: false },
    panel: { attribute: false },
    _view: { state: true },
  };

  static override styles = [
    shared,
    css`
      :host {
        background: var(--primary-background-color, #fafafa);
        min-height: 100vh;
      }

      header {
        align-items: center;
        background: var(--app-header-background-color, var(--primary-color, #03a9f4));
        color: var(--app-header-text-color, var(--text-primary-color, #fff));
        display: flex;
        gap: var(--ha-space-2, 8px);
        min-height: var(--header-height, 56px);
        padding: 0 var(--ha-space-4, 16px);
      }

      header h1 {
        font-size: var(--ha-font-size-xl, 20px);
        font-weight: var(--ha-font-weight-normal, 400);
        margin: 0;
      }

      header button.menu {
        border: none;
        color: inherit;
        margin: 0;
        padding: var(--ha-space-2, 8px);
      }

      header button.menu svg {
        display: block;
        fill: currentColor;
        height: 24px;
        width: 24px;
      }

      nav {
        background: var(--card-background-color, #fff);
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        display: flex;
        gap: var(--ha-space-1, 4px);
        padding: 0 var(--ha-space-4, 16px);
      }

      nav button {
        border: none;
        border-bottom: 2px solid transparent;
        border-radius: 0;
        color: var(--secondary-text-color, #727272);
        margin: 0;
        padding: var(--ha-space-3, 12px) var(--ha-space-4, 16px);
      }

      nav button[aria-selected="true"] {
        border-bottom-color: var(--primary-color, #03a9f4);
        color: var(--primary-color, #03a9f4);
      }

      main {
        margin: 0 auto;
        max-width: 1200px;
        padding: var(--ha-space-4, 16px);
      }

      :host([narrow]) main {
        padding: var(--ha-space-2, 8px);
      }
    `,
  ];

  declare hass: HomeAssistant | undefined;
  declare narrow: boolean;
  declare route: PanelRoute | undefined;
  declare panel: PanelInfo | undefined;
  declare _view: ViewName;

  private _unsubscribe: Promise<Unsubscribe | undefined> | undefined;

  constructor() {
    super();
    this.narrow = false;
    this._view = "routines";
  }

  override connectedCallback(): void {
    super.connectedCallback();
    this._subscribe();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    const pending = this._unsubscribe;
    this._unsubscribe = undefined;
    void pending?.then((unsubscribe) => unsubscribe?.());
  }

  protected override willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("route")) {
      this._view = viewOf(this.route) ?? this._view;
    }
    if (changed.has("hass")) {
      this._subscribe();
    }
  }

  /** Subscribe once while the panel is on the page and has a connection. */
  private _subscribe(): void {
    const hass = this.hass;
    if (hass === undefined || !this.isConnected || this._unsubscribe !== undefined) {
      return;
    }
    this._unsubscribe = subscribe(hass, (event) => this._heard(event)).catch(() => undefined);
  }

  private _heard(event: ManagerEvent): void {
    const root = this.renderRoot;
    switch (event.kind) {
      case "routine_changed":
        if (event.device_id !== null) {
          void root.querySelector("dr-routines-view")?.refreshRoutine(event.device_id);
        }
        break;
      case "schedule_changed":
        void root.querySelector("dr-today-view")?.refresh();
        break;
      case "settings_changed":
        void root.querySelector("dr-settings-view")?.refreshSettings();
        break;
      case "health_changed":
        root.querySelector("dr-settings-view")?.refreshHealth();
        break;
    }
  }

  private _show(view: ViewName): void {
    if (view === this._view) {
      return;
    }
    this._view = view;
    if (this.route !== undefined) {
      navigate(`${this.route.prefix}/${view}`);
    }
  }

  protected override render(): TemplateResult {
    const hass = this.hass;
    return html`
      <header>
        ${this.narrow
          ? html`<button
              class="menu"
              aria-label=${t(hass, "panel.menu")}
              @click=${() => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }))}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${MENU_ICON}></path></svg>
            </button>`
          : nothing}
        <h1>${t(hass, "panel.title")}</h1>
      </header>
      <nav role="tablist">
        ${VIEWS.map(
          (view) =>
            html`<button
              role="tab"
              data-view=${view}
              aria-selected=${view === this._view ? "true" : "false"}
              @click=${() => this._show(view)}
            >
              ${t(hass, TAB_KEYS[view])}
            </button>`,
        )}
      </nav>
      <main role="tabpanel">${this._renderView()}</main>
    `;
  }

  private _renderView(): TemplateResult {
    switch (this._view) {
      case "today":
        return html`<dr-today-view .hass=${this.hass} ?narrow=${this.narrow}></dr-today-view>`;
      case "settings":
        return html`<dr-settings-view .hass=${this.hass} ?narrow=${this.narrow}></dr-settings-view>`;
      default:
        return html`<dr-routines-view .hass=${this.hass} ?narrow=${this.narrow}></dr-routines-view>`;
    }
  }
}

if (!customElements.get("device-routines-panel")) {
  customElements.define("device-routines-panel", DeviceRoutinesPanel);
}

declare global {
  interface HTMLElementTagNameMap {
    "device-routines-panel": DeviceRoutinesPanel;
  }
}
