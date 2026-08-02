import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Format number with fixed decimal places.
 * @param n - Number to format
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted string or "—" for null/undefined
 */
export function formatNumber(n: number | undefined | null, decimals = 2): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

/**
 * Format the absolute distance between two prices as a signed percentage.
 *
 * Used by the result panel to render "距入场 +1.23%" / "距止损 -0.45%" style
 * badges beside the current-price cell so traders can see how far the live
 * market has moved from the recommended levels at a glance.
 *
 * Sign convention: positive = current is ABOVE the reference
 * (current - reference) / reference. For a long setup that's "above entry,
 * good for momentum" and for a stop it would flag "stop is closer now" — the
 * caller decides which framing applies.
 *
 * @param current - Latest market price
 * @param reference - Target price (entry / stop / target)
 * @param decimals - Fraction digits for the percentage (default: 2)
 * @returns Formatted "±X.XX%" string, or "—" when either input is missing.
 */
export function formatPriceDistance(
  current: number | undefined | null,
  reference: number | undefined | null,
  decimals = 2
): string {
  if (current == null || reference == null || reference === 0) return "—";
  const pct = ((current - reference) / reference) * 100;
  const sign = pct > 0 ? "+" : pct < 0 ? "" : "±";
  return `${sign}${pct.toFixed(decimals)}%`;
}

export function generateIdempotencyKey() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
