// Shared styles. Colors and spacing come only from Home Assistant theme variables, each
// with a fallback, so the console follows the user's theme and needs no `ha-*` element.

import { css } from "lit";

export const shared = css`
  :host {
    display: block;
    color: var(--primary-text-color, #212121);
    font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, sans-serif));
    font-size: var(--ha-font-size-m, 14px);
  }

  section {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--ha-card-border-radius, 12px);
    margin: 0 0 var(--ha-space-4, 16px);
    padding: var(--ha-space-4, 16px);
  }

  h2 {
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-medium, 500);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  p.hint {
    color: var(--secondary-text-color, #727272);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  .scroll {
    overflow-x: auto;
  }

  table {
    border-collapse: collapse;
    width: 100%;
  }

  th,
  td {
    border-bottom: 1px solid var(--divider-color, #e0e0e0);
    padding: var(--ha-space-2, 8px);
    text-align: start;
    vertical-align: top;
  }

  th {
    color: var(--secondary-text-color, #727272);
    font-weight: var(--ha-font-weight-medium, 500);
  }

  a {
    color: var(--primary-color, #03a9f4);
  }

  button {
    background: transparent;
    border: 1px solid var(--primary-color, #03a9f4);
    border-radius: var(--ha-border-radius-sm, 4px);
    color: var(--primary-color, #03a9f4);
    cursor: pointer;
    font: inherit;
    margin: 0 var(--ha-space-1, 4px) var(--ha-space-1, 4px) 0;
    padding: var(--ha-space-1, 4px) var(--ha-space-2, 8px);
  }

  button.primary {
    background: var(--primary-color, #03a9f4);
    color: var(--text-primary-color, #fff);
  }

  button:disabled {
    border-color: var(--disabled-text-color, #bdbdbd);
    color: var(--disabled-text-color, #bdbdbd);
    cursor: default;
  }

  input,
  select {
    background: var(--card-background-color, #fff);
    border: 1px solid var(--divider-color, #e0e0e0);
    border-radius: var(--ha-border-radius-sm, 4px);
    color: var(--primary-text-color, #212121);
    font: inherit;
    padding: var(--ha-space-1, 4px);
  }

  [aria-invalid="true"] {
    border-color: var(--error-color, #db4437);
    outline: 1px solid var(--error-color, #db4437);
  }

  .error {
    color: var(--error-color, #db4437);
    margin: var(--ha-space-2, 8px) 0;
  }

  .notice {
    color: var(--secondary-text-color, #727272);
    margin: var(--ha-space-2, 8px) 0;
  }

  .badge {
    border: 1px solid currentColor;
    border-radius: var(--ha-border-radius-pill, 999px);
    display: inline-block;
    font-size: var(--ha-font-size-s, 12px);
    margin-inline-start: var(--ha-space-1, 4px);
    padding: 0 var(--ha-space-2, 8px);
  }

  .muted {
    color: var(--secondary-text-color, #727272);
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: var(--ha-space-1, 4px);
    margin: 0 0 var(--ha-space-3, 12px);
  }

  .field.inline {
    align-items: center;
    flex-direction: row;
  }

  .field .description {
    color: var(--secondary-text-color, #727272);
    font-size: var(--ha-font-size-s, 12px);
  }
`;
