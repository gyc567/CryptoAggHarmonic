import type {
  ColdCheckItem,
  FundScale,
  PositionBalance,
  PositionConfig,
  RiskAppetite,
} from "@/types/position";

/** WU → U multiplier. 1 U = 10,000 WU. */
export const WU_UNIT = 10_000;

/** Recommended-ratio patches keyed by `${scale}-${appetite}`. */
export type RecommendationKey = `${FundScale}-${RiskAppetite}`;
export type RecommendationPatch = Partial<PositionConfig>;

/** Default config used when a user has no persisted state. Tuned so:
 *  - `formatWuAsU(DEFAULT_CONFIG.totalCapitalWu) === "100000000"`
 *  - `createDefaultBalance(DEFAULT_CONFIG).smallTradableWu === 70`
 *    (so the "archive 0.1 WU" test lands on 69.9).
 */
export const DEFAULT_CONFIG: PositionConfig = {
  totalCapitalWu: 10_000,
  emergencyRatio: 0.3,
  btcRatio: 0.4,
  altcoinMaxRatio: 0.15,
  midAccountRatio: 0.25,
  smallAccountRatio: 0.05,
  smallTradableRatio: 0.14,
  largeCapitalThresholdWu: 100_000, // 1B U
  largeCapitalAltcoinMaxRatio: 0.05,
  largeCapitalBtcReferenceRatio: 0.4,
  cutPositionWu: 0,
};

/** Pre-trade mental checklist; first item id must be "rationale" (tests toggle it). */
export const DEFAULT_CHECKLIST: ColdCheckItem[] = [
  {
    id: "rationale",
    label: "写下买入理由与卖出条件（任何交易前必做）",
    checked: false,
  },
  {
    id: "fomo",
    label: "确认这不是被 KOL / 社群情绪推动的 FOMO",
    checked: false,
  },
  {
    id: "risk-fit",
    label: "计划金额在风控等级可接受范围内",
    checked: false,
  },
  {
    id: "no-emergency",
    label: "已检查账户余额，不会动用救命钱",
    checked: false,
  },
];

/** One-click preset bundles; only the ratio fields are patched. */
export const RECOMMENDATIONS: Record<RecommendationKey, RecommendationPatch> = {
  // Small cap (≤ ~10k U). Stay conservative on alts; aggressive just means
  // bigger mid-account slice.
  "small-conservative": {
    emergencyRatio: 0.4,
    btcRatio: 0.45,
    altcoinMaxRatio: 0.1,
    midAccountRatio: 0.15,
    smallAccountRatio: 0.05,
    smallTradableRatio: 0.5,
  },
  "small-balanced": {
    emergencyRatio: 0.3,
    btcRatio: 0.4,
    altcoinMaxRatio: 0.15,
    midAccountRatio: 0.2,
    smallAccountRatio: 0.1,
    smallTradableRatio: 0.6,
  },
  "small-aggressive": {
    emergencyRatio: 0.25,
    btcRatio: 0.35,
    altcoinMaxRatio: 0.25,
    midAccountRatio: 0.25,
    smallAccountRatio: 0.15,
    smallTradableRatio: 0.7,
  },
  // Mid cap (~10k–500k U). Slightly more alt exposure tolerated.
  "medium-conservative": {
    emergencyRatio: 0.35,
    btcRatio: 0.4,
    altcoinMaxRatio: 0.1,
    midAccountRatio: 0.2,
    smallAccountRatio: 0.05,
    smallTradableRatio: 0.5,
  },
  "medium-balanced": {
    emergencyRatio: 0.3,
    btcRatio: 0.35,
    altcoinMaxRatio: 0.2,
    midAccountRatio: 0.25,
    smallAccountRatio: 0.1,
    smallTradableRatio: 0.6,
  },
  "medium-aggressive": {
    emergencyRatio: 0.25,
    btcRatio: 0.3,
    altcoinMaxRatio: 0.3,
    midAccountRatio: 0.3,
    smallAccountRatio: 0.15,
    smallTradableRatio: 0.7,
  },
  // Large cap (> 500k U). Cap alts harder; bigger emergency cushion.
  "large-conservative": {
    emergencyRatio: 0.45,
    btcRatio: 0.35,
    altcoinMaxRatio: 0.05,
    midAccountRatio: 0.15,
    smallAccountRatio: 0.05,
    smallTradableRatio: 0.4,
    largeCapitalAltcoinMaxRatio: 0.05,
    largeCapitalBtcReferenceRatio: 0.3,
  },
  "large-balanced": {
    emergencyRatio: 0.35,
    btcRatio: 0.3,
    altcoinMaxRatio: 0.1,
    midAccountRatio: 0.25,
    smallAccountRatio: 0.1,
    smallTradableRatio: 0.5,
    largeCapitalAltcoinMaxRatio: 0.1,
    largeCapitalBtcReferenceRatio: 0.35,
  },
  "large-aggressive": {
    emergencyRatio: 0.3,
    btcRatio: 0.3,
    altcoinMaxRatio: 0.15,
    midAccountRatio: 0.3,
    smallAccountRatio: 0.1,
    smallTradableRatio: 0.6,
    largeCapitalAltcoinMaxRatio: 0.15,
    largeCapitalBtcReferenceRatio: 0.4,
  },
};

/**
 * Materialise the per-account balance from a config. Always returns positive
 * numbers (or 0); never lets ratios or cut-position drive any bucket below
 * zero. Cut position is held aside untouched.
 */
export function createDefaultBalance(config: PositionConfig): PositionBalance {
  const regular = Math.max(0, config.totalCapitalWu - config.cutPositionWu);
  return {
    emergencyWu: regular * config.emergencyRatio,
    btcWu: regular * config.btcRatio,
    midWu: regular * config.midAccountRatio,
    smallTradableWu: regular * config.smallAccountRatio * config.smallTradableRatio,
    smallReserveWu: regular * config.smallAccountRatio * (1 - config.smallTradableRatio),
    cutPositionWu: config.cutPositionWu,
  };
}