import { beforeEach, describe, expect, it } from "vitest";

import { applyTextSize, otherTextSize } from "./text-size";

describe("applyTextSize", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.textSize;
  });

  it("sets the large attribute", () => {
    applyTextSize("large");
    expect(document.documentElement.dataset.textSize).toBe("large");
  });

  it("sets normal for the normal value", () => {
    applyTextSize("normal");
    expect(document.documentElement.dataset.textSize).toBe("normal");
  });

  it("falls back to normal for anything unrecognised, including undefined", () => {
    applyTextSize(undefined);
    expect(document.documentElement.dataset.textSize).toBe("normal");

    applyTextSize("huge");
    expect(document.documentElement.dataset.textSize).toBe("normal");
  });
});

describe("otherTextSize", () => {
  it("toggles both ways", () => {
    expect(otherTextSize("normal")).toBe("large");
    expect(otherTextSize("large")).toBe("normal");
  });
});
