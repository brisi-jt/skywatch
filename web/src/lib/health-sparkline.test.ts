import { describe, expect, it } from "vitest";

import type { HeartbeatResource } from "./api/client";
import { MAX_TICKS, lastDrop, recentTicks, uptimeFraction } from "./health-sparkline";

const heartbeat = (recorded_at: string, capture_running: boolean): HeartbeatResource => ({
  recorded_at,
  capture_running,
  queue_depths: {},
  disk_free_gb: 20,
  llm_remaining: null,
  opensky_remaining: null,
});

describe("recentTicks", () => {
  it("returns nothing for an empty window", () => {
    expect(recentTicks([])).toEqual([]);
  });

  it("maps every snapshot when there are fewer than the cap", () => {
    const items = [heartbeat("2026-08-01T00:00:00Z", true), heartbeat("2026-08-01T00:15:00Z", false)];
    expect(recentTicks(items)).toEqual([
      { up: true, recorded_at: "2026-08-01T00:00:00Z" },
      { up: false, recorded_at: "2026-08-01T00:15:00Z" },
    ]);
  });

  it("keeps only the most recent snapshots once past the cap", () => {
    const items = Array.from({ length: MAX_TICKS + 5 }, (_, i) =>
      heartbeat(`2026-08-01T${String(i).padStart(2, "0")}:00:00Z`, true),
    );
    const ticks = recentTicks(items, MAX_TICKS);
    expect(ticks).toHaveLength(MAX_TICKS);
    expect(ticks[ticks.length - 1].recorded_at).toBe(items[items.length - 1].recorded_at);
  });
});

describe("uptimeFraction", () => {
  it("is null with no data", () => {
    expect(uptimeFraction([])).toBeNull();
  });

  it("is the share of snapshots where capture was running", () => {
    const items = [
      heartbeat("2026-08-01T00:00:00Z", true),
      heartbeat("2026-08-01T00:15:00Z", true),
      heartbeat("2026-08-01T00:30:00Z", false),
      heartbeat("2026-08-01T00:45:00Z", true),
    ];
    expect(uptimeFraction(items)).toBe(0.75);
  });
});

describe("lastDrop", () => {
  it("is null when capture has never stopped", () => {
    const items = [heartbeat("2026-08-01T00:00:00Z", true), heartbeat("2026-08-01T00:15:00Z", true)];
    expect(lastDrop(items)).toBeNull();
  });

  it("finds the most recent snapshot where capture had stopped", () => {
    const items = [
      heartbeat("2026-08-01T00:00:00Z", false),
      heartbeat("2026-08-01T00:15:00Z", true),
      heartbeat("2026-08-01T00:30:00Z", false),
      heartbeat("2026-08-01T00:45:00Z", true),
    ];
    expect(lastDrop(items)?.recorded_at).toBe("2026-08-01T00:30:00Z");
  });
});
