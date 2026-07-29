/**
 * Position calculators — pure functions over (config, balance, ...).
 *
 * Layering:
 *   - `computeBuckets`        → 5 account buckets with device + colour
 *   - `computeRiskLevels`     → 6 escalating thresholds (0–5)
 *   - `computeRiskLevel`      → pick the level a given planned trade lands in
 *   - `simulateWhatIf`        → drain accounts in priority order
 *   - `computeValidation`     → boolean checks (sum, ranges, caps)
 *   - `computeDiagnostics`    → soft warnings/info (empty for sane defaults)
 */
import type {
  AccountBucket,
  DiagnosticItem,
  PositionBalance,
  PositionConfig,
  RiskLevel,
  ValidationResult,
  WhatIfResult,
} from "@/types/position";

const BUCKET_COLORS = {
  emergency: "#22c55e",
  btc: "#f59e0b",
  mid: "#06b6d4",
  smallTradable: "#8b5cf6",
  smallReserve: "#ec4899",
} as const;

const BUCKET_DEVICES = {
  emergency: "冷钱包/独立账户",
  btc: "交易所主账户",
  mid: "手机/备用设备",
  smallTradable: "测试网/小资金账户",
  smallReserve: "钱包储备",
} as const;

/** 5 buckets in fixed order: emergency → BTC → mid → smallTradable → smallReserve. */
export function computeBuckets(
  config: PositionConfig,
  balance: PositionBalance,
): AccountBucket[] {
  const regular = Math.max(0, config.totalCapitalWu - config.cutPositionWu);
  const total = config.totalCapitalWu;
  const safeRegular = regular > 0 ? regular : 1;
  const safeTotal = total > 0 ? total : 1;

  const build = (
    key: keyof typeof BUCKET_COLORS,
    label: string,
    amountWu: number,
  ): AccountBucket => ({
    key,
    label,
    amountWu,
    ratioOfRegular: regular > 0 ? amountWu / safeRegular : 0,
    ratioOfTotal: total > 0 ? amountWu / safeTotal : 0,
    device: BUCKET_DEVICES[key],
    color: BUCKET_COLORS[key],
  });

  return [
    build("emergency", "救命钱", balance.emergencyWu),
    build("btc", "BTC 趋势仓", balance.btcWu),
    build("mid", "中账户", balance.midWu),
    build("smallTradable", "小账户 · 可交易", balance.smallTradableWu),
    build("smallReserve", "小账户 · 备用", balance.smallReserveWu),
  ];
}

/** 6 levels (0–5). Each level's minWu/maxWu are running cumulative balances. */
export function computeRiskLevels(
  config: PositionConfig,
  balance: PositionBalance,
): RiskLevel[] {
  const st = Math.max(0, balance.smallTradableWu);
  const sr = Math.max(0, balance.smallTradableWu + balance.smallReserveWu);
  const mid = Math.max(sr, balance.smallTradableWu + balance.smallReserveWu + balance.midWu);
  const btc = Math.max(
    mid,
    balance.smallTradableWu + balance.smallReserveWu + balance.midWu + balance.btcWu,
  );
  // unused but kept for symmetry with the ladder
  void config;

  return [
    {
      level: 0,
      label: "0 级",
      minWu: 0,
      maxWu: st * 0.5,
      trouble: "无额外麻烦",
      cooldown: "至少确认逻辑",
    },
    {
      level: 1,
      label: "1 级",
      minWu: st * 0.5,
      maxWu: st,
      trouble: "消耗小账户可交易部分",
      cooldown: "冷静 30 分钟",
    },
    {
      level: 2,
      label: "2 级",
      minWu: st,
      maxWu: sr,
      trouble: "触及小账户备用金",
      cooldown: "冷静 2 小时",
    },
    {
      level: 3,
      label: "3 级",
      minWu: sr,
      maxWu: mid,
      trouble: "触及中账户",
      cooldown: "冷静 24 小时",
    },
    {
      level: 4,
      label: "4 级",
      minWu: mid,
      maxWu: btc,
      trouble: "触及 BTC 趋势仓",
      cooldown: "冷静 1 周",
    },
    {
      level: 5,
      label: "5 级",
      minWu: btc,
      maxWu: Infinity,
      trouble: "动用救命钱",
      cooldown: "原则上禁止",
    },
  ];
}

/** Highest level whose minWu ≤ plannedTrade. */
export function computeRiskLevel(
  config: PositionConfig,
  balance: PositionBalance,
  plannedTrade: number,
): RiskLevel {
  const levels = computeRiskLevels(config, balance);
  let chosen = levels[0];
  for (const lvl of levels) {
    if (plannedTrade >= lvl.minWu) chosen = lvl;
  }
  return chosen;
}

/**
 * Drain accounts in priority order:
 *   smallTradable → smallReserve → mid → btc → emergency.
 * Returns per-bucket consumed + remaining, plus a flag for emergency touch.
 */
export function simulateWhatIf(
  _config: PositionConfig,
  balance: PositionBalance,
  tradeWu: number,
): WhatIfResult {
  const remaining = {
    emergencyWu: balance.emergencyWu,
    btcWu: balance.btcWu,
    midWu: balance.midWu,
    smallTradableWu: balance.smallTradableWu,
    smallReserveWu: balance.smallReserveWu,
  };
  const consumed = {
    emergencyWu: 0,
    btcWu: 0,
    midWu: 0,
    smallTradableWu: 0,
    smallReserveWu: 0,
  };

  let toConsume = tradeWu;

  const drain = (key: keyof typeof remaining): void => {
    if (toConsume <= 0) return;
    const available = remaining[key];
    const take = Math.min(available, toConsume);
    remaining[key] -= take;
    consumed[key] = take;
    toConsume -= take;
  };

  drain("smallTradableWu");
  drain("smallReserveWu");
  drain("midWu");
  drain("btcWu");
  drain("emergencyWu");

  const remainingTotalWu =
    remaining.emergencyWu +
    remaining.btcWu +
    remaining.midWu +
    remaining.smallTradableWu +
    remaining.smallReserveWu;

  return {
    tradeWu,
    consumedEmergencyWu: consumed.emergencyWu,
    consumedBtcWu: consumed.btcWu,
    consumedMidWu: consumed.midWu,
    consumedSmallTradableWu: consumed.smallTradableWu,
    consumedSmallReserveWu: consumed.smallReserveWu,
    remainingEmergencyWu: remaining.emergencyWu,
    remainingBtcWu: remaining.btcWu,
    remainingMidWu: remaining.midWu,
    remainingSmallTradableWu: remaining.smallTradableWu,
    remainingSmallReserveWu: remaining.smallReserveWu,
    remainingTotalWu,
    touchesEmergency: consumed.emergencyWu > 0,
  };
}

/** 4 invariant checks. Returns 4 items so callers can render a count. */
export function computeValidation(config: PositionConfig): ValidationResult[] {
  const sumRatios =
    config.emergencyRatio +
    config.btcRatio +
    config.midAccountRatio +
    config.smallAccountRatio;

  return [
    {
      id: "sum-of-allocations",
      label: "资金总配比 ≤ 100%",
      passed: sumRatios <= 1.0001,
      detail: `当前合计 ${(sumRatios * 100).toFixed(0)}%`,
    },
    {
      id: "small-tradable-range",
      label: "小账户可交易比例在 0~1 之间",
      passed: config.smallTradableRatio >= 0 && config.smallTradableRatio <= 1,
      detail: `当前 ${(config.smallTradableRatio * 100).toFixed(0)}%`,
    },
    {
      id: "altcoin-cap",
      label: "山寨币上限未超过中账户",
      passed: config.altcoinMaxRatio <= config.midAccountRatio + 0.0001,
      detail: `山寨 ${(config.altcoinMaxRatio * 100).toFixed(0)}% / 中账户 ${(config.midAccountRatio * 100).toFixed(0)}%`,
    },
    {
      id: "emergency-positive",
      label: "救命钱比例 > 0",
      passed: config.emergencyRatio > 0,
      detail: `当前 ${(config.emergencyRatio * 100).toFixed(0)}%`,
    },
  ];
}

/** Soft warnings/info. Default config returns an empty list. */
export function computeDiagnostics(config: PositionConfig): DiagnosticItem[] {
  const items: DiagnosticItem[] = [];

  if (config.emergencyRatio < 0.2) {
    items.push({
      id: "low-emergency",
      severity: "warning",
      message: "救命钱比例过低（建议 ≥ 20%）",
      action: "提高 emergencyRatio",
    });
  }
  if (config.altcoinMaxRatio > 0.3) {
    items.push({
      id: "high-altcoin",
      severity: "warning",
      message: "山寨币上限过高（建议 ≤ 30%）",
      action: "降低 altcoinMaxRatio",
    });
  }
  if (config.smallAccountRatio > config.midAccountRatio) {
    items.push({
      id: "small-greater-than-mid",
      severity: "info",
      message: "小账户比例超过中账户",
      action: "考虑重新分配",
    });
  }

  return items;
}