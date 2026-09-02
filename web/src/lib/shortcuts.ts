/** Keyboard-shortcut dispatch guard.
 *
 * Global player shortcuts (space, arrows, j/k) must never fire while the
 * listener is typing into a form control or an editable region — otherwise
 * space scrolls a date picker or j/k mutate a text field. This decides,
 * from the event's target, whether a shortcut should be ignored. Pure so it
 * can be unit-tested without a real DOM.
 */

const TYPING_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

interface ShortcutTarget {
  tagName?: string;
  isContentEditable?: boolean;
}

export function isTypingTarget(target: ShortcutTarget | null | undefined): boolean {
  if (!target) return false;
  if (target.isContentEditable) return true;
  return target.tagName != null && TYPING_TAGS.has(target.tagName.toUpperCase());
}

/** The player actions a key can trigger; null when the key isn't a shortcut. */
export type ShortcutAction = "toggle" | "back5" | "forward5" | "next" | "prev";

export function shortcutFor(key: string): ShortcutAction | null {
  switch (key) {
    case " ":
    case "Spacebar": // older browsers report the space key this way
      return "toggle";
    case "ArrowLeft":
      return "back5";
    case "ArrowRight":
      return "forward5";
    case "j":
    case "J":
      return "next";
    case "k":
    case "K":
      return "prev";
    default:
      return null;
  }
}
