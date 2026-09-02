/**
 * The listening queue: pure, tested state for hands-free playback.
 *
 * A queue is an ordered list of clips plus a cursor. `index` points at the
 * playing clip; when it runs off the end the queue is "stopped" and
 * `currentItem` returns null (playback does not wrap). All transitions are
 * pure so the behaviour can be unit-tested without a real <audio> element.
 */

export interface QueueItem {
  id: number;
  title: string;
  subtitle: string;
}

export interface QueueState {
  items: QueueItem[];
  /** Cursor into `items`; `items.length` means "played past the end". */
  index: number;
}

export const emptyQueue: QueueState = { items: [], index: 0 };

export type QueueAction =
  | { type: "seed"; items: QueueItem[]; startId: number }
  | { type: "advance" }
  | { type: "remove"; id: number }
  | { type: "clear" };

/** The clip playing right now, or null when the queue is empty or finished. */
export function currentItem(state: QueueState): QueueItem | null {
  return state.items[state.index] ?? null;
}

/** Whether an `advance` would land on another clip rather than stopping. */
export function hasNext(state: QueueState): boolean {
  return state.index + 1 < state.items.length;
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case "seed": {
      const found = action.items.findIndex((item) => item.id === action.startId);
      return { items: action.items, index: found === -1 ? 0 : found };
    }
    case "advance": {
      // Clamp to items.length: one step past the last clip means "stopped".
      return { ...state, index: Math.min(state.index + 1, state.items.length) };
    }
    case "remove": {
      const removedAt = state.items.findIndex((item) => item.id === action.id);
      if (removedAt === -1) return state;
      const items = state.items.filter((item) => item.id !== action.id);
      // Removing something before the cursor shifts the cursor left so it keeps
      // pointing at the same clip. Removing the current clip leaves the cursor
      // where it is, which now points at what used to be the next clip.
      const index = removedAt < state.index ? state.index - 1 : state.index;
      return { items, index: Math.min(index, items.length) };
    }
    case "clear":
      return { items: [], index: 0 };
  }
}
