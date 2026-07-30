import { describe, expect, it } from "vitest";
import { formatNumber } from "./utils";

describe("formatNumber", () => {
  it("formats integer with default 2 decimal places", () => {
    expect(formatNumber(110)).toBe("110.00");
    expect(formatNumber(99)).toBe("99.00");
  });

  it("formats float with default 2 decimal places", () => {
    expect(formatNumber(110.5)).toBe("110.50");
    expect(formatNumber(99.123)).toBe("99.12");
  });

  it("handles null and undefined", () => {
    expect(formatNumber(null)).toBe("—");
    expect(formatNumber(undefined)).toBe("—");
  });

  it("respects custom decimal places", () => {
    expect(formatNumber(1.5, 0)).toBe("2");
    expect(formatNumber(1.555, 3)).toBe("1.555");
    expect(formatNumber(100, 0)).toBe("100");
  });
});
