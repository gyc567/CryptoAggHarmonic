import { describe, expect, it } from "vitest";
import { formatNumber, formatPriceDistance } from "@/lib/utils";

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

  it("respects decimals override", () => {
    expect(formatNumber(99.123, 4)).toBe("99.1230");
  });
});

describe("formatPriceDistance", () => {
  it("renders positive delta with a plus sign", () => {
    // current is 1% above reference
    expect(formatPriceDistance(101, 100)).toBe("+1.00%");
  });

  it("renders negative delta without a plus sign", () => {
    expect(formatPriceDistance(99, 100)).toBe("-1.00%");
  });

  it("renders zero delta with a plus-minus sign", () => {
    expect(formatPriceDistance(100, 100)).toBe("±0.00%");
  });

  it("respects the decimals override", () => {
    expect(formatPriceDistance(100.123, 100, 3)).toBe("+0.123%");
    expect(formatPriceDistance(100.123, 100, 1)).toBe("+0.1%");
  });

  it("returns em-dash when either input is missing", () => {
    expect(formatPriceDistance(undefined, 100)).toBe("—");
    expect(formatPriceDistance(100, undefined)).toBe("—");
    expect(formatPriceDistance(null, 100)).toBe("—");
    expect(formatPriceDistance(100, null)).toBe("—");
  });

  it("returns em-dash when reference is zero (avoids divide-by-zero)", () => {
    // 0 / 0 is NaN; we'd rather show "—" than "NaN%".
    expect(formatPriceDistance(100, 0)).toBe("—");
  });
});
