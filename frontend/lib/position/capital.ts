/**
 * WU ↔ U helpers used by the capital input in PositionConfigPanel.
 * 1 U = 10,000 WU (matches WU_UNIT in ./defaults).
 */
import { WU_UNIT } from "./defaults";

/** Format a WU amount as the U string shown in the input (integer, no decimals). */
export function formatWuAsU(wu: number): string {
  return Math.round(wu * WU_UNIT).toString();
}

export type CapitalParseResult =
  | { ok: true; wu: number; warning?: string }
  | { ok: false; reason: string };

/** Below this WU amount, allocation is meaningless (≈ < 100 U). */
const MIN_USEFUL_WU = 0.01;

/**
 * Parse a free-form U input string. Returns a discriminated union so callers
 * can branch on `ok` and surface `reason` (display) vs `warning` (advisory).
 */
export function parseCapitalInput(raw: string): CapitalParseResult {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { ok: false, reason: "empty" };
  }
  const num = Number(trimmed);
  if (!Number.isFinite(num)) {
    return { ok: false, reason: "请输入有效数字" };
  }
  if (num <= 0) {
    return { ok: false, reason: "必须大于 0" };
  }
  const wu = num / WU_UNIT;
  if (wu < MIN_USEFUL_WU) {
    return {
      ok: true,
      wu,
      warning: "金额过小，分配将失去参考意义",
    };
  }
  return { ok: true, wu };
}