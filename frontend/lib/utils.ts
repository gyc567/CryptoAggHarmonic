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

export function generateIdempotencyKey() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
