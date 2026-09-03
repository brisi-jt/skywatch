/** The A/A+ toggle: how the dashboard's base text size reaches the DOM.
 *
 * The root `font-size` (18px normal, 20px large) lives in a CSS rule keyed
 * off `html[data-text-size="large"]`; every rem-based size in the app scales
 * from it. This module is the one place that reads/writes that attribute.
 */

export type TextSize = "normal" | "large";

/** Sets the root attribute the CSS token switches on. Safe to call
 * before the setting has loaded — anything but "large" renders normal. */
export function applyTextSize(size: string | undefined): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.textSize = size === "large" ? "large" : "normal";
}

/** The other choice in the two-way A/A+ toggle. */
export function otherTextSize(size: TextSize): TextSize {
  return size === "large" ? "normal" : "large";
}
