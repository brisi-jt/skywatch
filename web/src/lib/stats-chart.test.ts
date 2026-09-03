import { describe, expect, it } from "vitest";

import type {
  AirlineCount,
  DailyMovementCount,
  HourlyHeatCell,
} from "./api/client";
import {
  airlineFractions,
  heatBucket,
  heatLookup,
  maxHeatCount,
  polylinePoints,
  trendPoints,
} from "./stats-chart";

const daily = (values: Array<[string, number, number]>): DailyMovementCount[] =>
  values.map(([date, total, interesting]) => ({
    date,
    total_count: total,
    interesting_count: interesting,
  }));

describe("trendPoints", () => {
  it("returns nothing for an empty window", () => {
    expect(trendPoints([])).toEqual([]);
  });

  it("normalises counts against the busiest day in the window", () => {
    const points = trendPoints(
      daily([
        ["2026-08-01", 4, 1],
        ["2026-08-02", 8, 4],
      ]),
    );

    expect(points).toHaveLength(2);
    expect(points[0]).toEqual({ x: 0, yTotal: 0.5, yInteresting: 0.125 });
    expect(points[1]).toEqual({ x: 1, yTotal: 1, yInteresting: 0.5 });
  });

  it("never divides by zero when every day is silent", () => {
    const points = trendPoints(daily([["2026-08-01", 0, 0]]));
    expect(points[0]).toEqual({ x: 0, yTotal: 0, yInteresting: 0 });
  });

  it("places a single day at the start of the axis", () => {
    const points = trendPoints(daily([["2026-08-01", 2, 0]]));
    expect(points[0].x).toBe(0);
  });
});

describe("polylinePoints", () => {
  it("maps normalised points into a pixel viewport, y-flipped", () => {
    const points = trendPoints(
      daily([
        ["2026-08-01", 0, 0],
        ["2026-08-02", 10, 0],
      ]),
    );

    const svgPoints = polylinePoints(points, "yTotal", 100, 50);

    // y=0 (no movements) draws at the bottom of the chart (height); y=1 draws at the top (0).
    expect(svgPoints).toBe("0.0,50.0 100.0,0.0");
  });
});

describe("heatBucket", () => {
  it("buckets zero and an empty grid to 0", () => {
    expect(heatBucket(0, 10)).toBe(0);
    expect(heatBucket(5, 0)).toBe(0);
  });

  it("buckets proportionally to the grid's busiest cell", () => {
    expect(heatBucket(1, 10)).toBe(1);
    expect(heatBucket(3, 10)).toBe(2);
    expect(heatBucket(6, 10)).toBe(3);
    expect(heatBucket(10, 10)).toBe(4);
  });
});

describe("heatLookup / maxHeatCount", () => {
  const cells: HourlyHeatCell[] = [
    { hour: 8, freq_id: 1, count: 3 },
    { hour: 20, freq_id: 2, count: 7 },
  ];

  it("keys counts by frequency and hour", () => {
    const lookup = heatLookup(cells);
    expect(lookup.get("1:8")).toBe(3);
    expect(lookup.get("2:20")).toBe(7);
    expect(lookup.get("1:20")).toBeUndefined();
  });

  it("finds the busiest cell in the grid", () => {
    expect(maxHeatCount(cells)).toBe(7);
    expect(maxHeatCount([])).toBe(0);
  });
});

describe("airlineFractions", () => {
  it("scales every count against the busiest airline", () => {
    const airlines: AirlineCount[] = [
      { airline_name: "Ryanair", count: 8 },
      { airline_name: "Wizz Air", count: 2 },
    ];

    const scaled = airlineFractions(airlines);

    expect(scaled[0].fraction).toBe(1);
    expect(scaled[1].fraction).toBe(0.25);
  });

  it("does not divide by zero for an empty list", () => {
    expect(airlineFractions([])).toEqual([]);
  });
});
