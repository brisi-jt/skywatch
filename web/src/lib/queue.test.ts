import { describe, expect, it } from "vitest";

import {
  currentItem,
  emptyQueue,
  hasNext,
  queueReducer,
  type QueueItem,
} from "./queue";

const clip = (id: number): QueueItem => ({
  id,
  title: `clip ${id}`,
  subtitle: `sub ${id}`,
});

const list = [clip(1), clip(2), clip(3)];

describe("queueReducer", () => {
  it("starts empty with no current item", () => {
    expect(currentItem(emptyQueue)).toBeNull();
    expect(hasNext(emptyQueue)).toBe(false);
  });

  it("seeds from a list starting at the chosen clip", () => {
    const state = queueReducer(emptyQueue, { type: "seed", items: list, startId: 2 });
    expect(currentItem(state)?.id).toBe(2);
    expect(hasNext(state)).toBe(true);
  });

  it("seeds at the head when the start id is absent from the list", () => {
    const state = queueReducer(emptyQueue, { type: "seed", items: list, startId: 99 });
    expect(currentItem(state)?.id).toBe(1);
  });

  it("advances to the next clip", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 1 });
    const next = queueReducer(seeded, { type: "advance" });
    expect(currentItem(next)?.id).toBe(2);
    expect(hasNext(next)).toBe(true);
  });

  it("stops at the end rather than wrapping", () => {
    let state = queueReducer(emptyQueue, { type: "seed", items: list, startId: 3 });
    expect(hasNext(state)).toBe(false);
    state = queueReducer(state, { type: "advance" });
    expect(currentItem(state)).toBeNull();
    // advancing past the end is idempotent
    state = queueReducer(state, { type: "advance" });
    expect(currentItem(state)).toBeNull();
  });

  it("removes an upcoming clip without moving the current one", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 1 });
    const state = queueReducer(seeded, { type: "remove", id: 3 });
    expect(currentItem(state)?.id).toBe(1);
    expect(state.items.map((i) => i.id)).toEqual([1, 2]);
  });

  it("removes an earlier clip and keeps pointing at the same current clip", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 3 });
    const state = queueReducer(seeded, { type: "remove", id: 1 });
    expect(currentItem(state)?.id).toBe(3);
    expect(state.items.map((i) => i.id)).toEqual([2, 3]);
  });

  it("removing the current clip drops onto the next one", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 2 });
    const state = queueReducer(seeded, { type: "remove", id: 2 });
    expect(currentItem(state)?.id).toBe(3);
  });

  it("removing the last current clip stops playback", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 3 });
    const state = queueReducer(seeded, { type: "remove", id: 3 });
    expect(currentItem(state)).toBeNull();
  });

  it("clears back to empty", () => {
    const seeded = queueReducer(emptyQueue, { type: "seed", items: list, startId: 1 });
    const state = queueReducer(seeded, { type: "clear" });
    expect(currentItem(state)).toBeNull();
    expect(state.items).toEqual([]);
  });
});
