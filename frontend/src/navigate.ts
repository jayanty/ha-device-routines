// In app navigation, as Home Assistant's own frontend does it: push the path and tell the
// app's router with a `location-changed` event. Links keep their `href`, so opening one
// in a new tab still works.

export function navigate(path: string): void {
  history.pushState(null, "", path);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

/** A click handler for an `<a href>`: a plain left click navigates inside the app. */
export function followLink(event: MouseEvent): void {
  const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
  if (event.defaultPrevented || event.button !== 0 || modified) {
    return;
  }
  const anchor = event.currentTarget;
  if (!(anchor instanceof HTMLAnchorElement)) {
    return;
  }
  event.preventDefault();
  navigate(anchor.getAttribute("href") ?? "/");
}
