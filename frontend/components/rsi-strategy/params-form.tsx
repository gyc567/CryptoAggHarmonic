"use client";

import { cn } from "@/lib/utils";
import type {
  RsiTrendInterval,
  RsiTrendMarket,
  RsiTrendRequestParams,
  RsiTrendZone,
} from "@/lib/api-rsi-strategy";

const CRYPTO_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"];
const STOCK_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "^GSPC", "^IXIC"];

const CRYPTO_INTERVALS: { value: RsiTrendInterval; label: string }[] = [
  { value: "4h", label: "4小时 (推荐)" },
  { value: "1h", label: "1小时" },
  { value: "1d", label: "日线" },
];
const STOCK_INTERVALS: { value: RsiTrendInterval; label: string }[] = [
  { value: "1d", label: "日线 (推荐)" },
  { value: "1w", label: "周线" },
];

const RSI_ZONE_OPTIONS: { value: RsiTrendZone; label: string; hint: string }[] = [
  { value: "extreme", label: "极端区 30/70", hint: "经典 RSI 超卖/超买，信号少但过滤强" },
  { value: "pullback", label: "回调区 40/60", hint: "强势趋势中更常见的浅回调，信号更多" },
];

interface ParamsFormProps {
  params: RsiTrendRequestParams;
  loading: boolean;
  onChange: <K extends keyof RsiTrendRequestParams>(key: K, value: RsiTrendRequestParams[K]) => void;
}

export function ParamsForm({ params, loading, onChange }: ParamsFormProps) {
  const isCrypto = params.market === "binance";
  const intervalOptions = isCrypto ? CRYPTO_INTERVALS : STOCK_INTERVALS;
  const symbolOptions = isCrypto ? CRYPTO_SYMBOLS : STOCK_SYMBOLS;

  const handleMarketChange = (market: RsiTrendMarket) => {
    onChange("market", market);
    // Reset market-dependent fields to valid defaults.
    onChange("symbol", market === "binance" ? CRYPTO_SYMBOLS[0] : STOCK_SYMBOLS[0]);
    onChange("interval", market === "binance" ? "4h" : "1d");
  };

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">市场</label>
        <select
          value={params.market}
          onChange={(e) => handleMarketChange(e.target.value as RsiTrendMarket)}
          disabled={loading}
          className="input-surface"
        >
          <option value="binance">加密货币 (Binance)</option>
          <option value="yahoo">股票 (Yahoo)</option>
        </select>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">标的</label>
        <input
          list="rsi-strategy-symbols"
          value={params.symbol}
          onChange={(e) => onChange("symbol", e.target.value.toUpperCase())}
          disabled={loading}
          className="input-surface uppercase"
          placeholder={isCrypto ? "如 BTCUSDT" : "如 AAPL"}
        />
        <datalist id="rsi-strategy-symbols">
          {symbolOptions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">周期</label>
        <select
          value={params.interval}
          onChange={(e) => onChange("interval", e.target.value as RsiTrendInterval)}
          disabled={loading}
          className="input-surface"
        >
          {intervalOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          ATR 止损倍数（{params.atr_mult.toFixed(1)}）
        </label>
        <input
          type="range"
          min={0.5}
          max={3.0}
          step={0.1}
          value={params.atr_mult}
          onChange={(e) => onChange("atr_mult", Number(e.target.value))}
          disabled={loading}
          className="mt-3 w-full accent-primary"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          RSI 入场区域
        </label>
        <select
          value={params.rsi_zone}
          onChange={(e) => onChange("rsi_zone", e.target.value as RsiTrendZone)}
          disabled={loading}
          className="input-surface"
        >
          {RSI_ZONE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label} — {o.hint}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          盈亏比（1:{params.reward_risk.toFixed(1)}）
        </label>
        <input
          type="range"
          min={1.0}
          max={5.0}
          step={0.5}
          value={params.reward_risk}
          onChange={(e) => onChange("reward_risk", Number(e.target.value))}
          disabled={loading}
          className="mt-3 w-full accent-primary"
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">
          最低质量分（{Math.round(params.min_quality_score)}）
        </label>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          value={params.min_quality_score}
          onChange={(e) => onChange("min_quality_score", Number(e.target.value))}
          disabled={loading}
          className="mt-3 w-full accent-primary"
        />
      </div>

      <label className={cn("flex items-center gap-2 text-sm text-foreground sm:col-span-2")}>
        <input
          type="checkbox"
          checked={params.use_ema50}
          onChange={(e) => onChange("use_ema50", e.target.checked)}
          disabled={loading}
          className="h-4 w-4 accent-primary"
        />
        EMA50 确认（价格需同时站上/跌破 EMA50）
      </label>

      <label className="flex items-center gap-2 text-sm text-foreground sm:col-span-2">
        <input
          type="checkbox"
          checked={params.require_candle_color}
          onChange={(e) => onChange("require_candle_color", e.target.checked)}
          disabled={loading}
          className="h-4 w-4 accent-primary"
        />
        K线颜色确认（多单收阳 / 空单收阴）
      </label>
    </div>
  );
}
