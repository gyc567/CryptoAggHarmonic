/**
 * TradingView data bridge for the pyharmonics-gpt backend.
 *
 * Wraps @mathieuc/tradingview in a small HTTP service so the Python
 * backend can fetch candles without running Node code itself.
 *
 * Environment:
 *   PORT              - HTTP port (default 5002)
 *   TRADINGVIEW_DEBUG - set to "1" to enable package debug logs
 */
import express from 'express';
import cors from 'cors';
import TradingView from '@mathieuc/tradingview';

const app = express();
app.use(cors());
app.use(express.json());

const PORT = process.env.PORT || 5002;
const DEBUG = process.env.TRADINGVIEW_DEBUG === '1';

// Map our interval strings to TradingView timeframe strings (minutes or D/W)
const INTERVAL_MAP = {
  '1m': '1',
  '5m': '5',
  '15m': '15',
  '30m': '30',
  '1h': '60',
  '2h': '120',
  '4h': '240',
  '1d': 'D',
  '1w': 'W',
};

const REVERSE_INTERVAL_MAP = Object.fromEntries(
  Object.entries(INTERVAL_MAP).map(([k, v]) => [v, k])
);

function toCandleArray(periods) {
  if (!Array.isArray(periods)) return [];
  return periods.map((p) => ({
    open_time: p.time * 1000,
    open: p.open,
    high: p.high,
    low: p.low,
    close: p.close,
    volume: p.volume || 0,
    close_time: (p.time + 1) * 1000,
    dts: new Date(p.time * 1000).toISOString(),
  }));
}

// Reuse one client; @mathieuc/tradingview manages a single WS connection.
const client = new TradingView.Client({ DEBUG });

client.onError((...err) => {
  console.error('TradingView client error:', ...err);
});

client.onDisconnected(() => {
  console.warn('TradingView client disconnected');
});

function makeChartSession() {
  return new client.Session.Chart();
}

app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    connected: client.isOpen,
    logged: client.isLogged,
  });
});

/**
 * GET /candles
 * Query params:
 *   symbol  - e.g. BTCUSDT (required)
 *   market  - e.g. binance, nasdaq, otc (default binance)
 *   interval- 1m,5m,15m,30m,1h,2h,4h,1d,1w (default 4h)
 *   limit   - number of candles (default 500, max 5000)
 *   to      - optional Unix timestamp (seconds) to fetch backwards from
 */
app.get('/candles', async (req, res) => {
  const {
    symbol,
    market = 'binance',
    interval = '4h',
    limit = '500',
    to,
  } = req.query;

  if (!symbol) {
    return res.status(400).json({ success: false, error: 'symbol is required' });
  }

  const tvInterval = INTERVAL_MAP[interval];
  if (!tvInterval) {
    return res.status(400).json({
      success: false,
      error: `unsupported interval: ${interval}`,
    });
  }

  const tvSymbol = symbol.includes(':')
    ? symbol.toUpperCase()
    : `${market.toUpperCase()}:${symbol.toUpperCase()}`;

  const range = Math.min(parseInt(limit, 10) || 500, 5000);

  try {
    const chart = makeChartSession();
    const candles = await new Promise((resolve, reject) => {
      let settled = false;

      const cleanup = () => {
        try {
          chart.delete();
        } catch {
          // ignore
        }
      };

      chart.onError((...err) => {
        if (!settled) {
          settled = true;
          cleanup();
          reject(new Error(err.join(' ') || 'TradingView chart error'));
        }
      });

      chart.onUpdate(() => {
        if (settled) return;
        if (!chart.periods || chart.periods.length === 0) return;
        settled = true;
        const data = [...chart.periods];
        cleanup();
        resolve(data);
      });

      const options = {
        timeframe: tvInterval,
        range,
      };
      if (to) {
        options.to = parseInt(to, 10);
      }

      chart.setMarket(tvSymbol, options);

      setTimeout(() => {
        if (!settled) {
          settled = true;
          cleanup();
          reject(new Error('TradingView data timeout'));
        }
      }, 6000);
    });

    res.json({
      success: true,
      source: 'tradingview',
      symbol: tvSymbol,
      interval,
      candles: toCandleArray(candles),
    });
  } catch (err) {
    console.error('TradingView fetch error:', err.message);
    res.status(503).json({
      success: false,
      error: err.message,
      source: 'tradingview',
    });
  }
});

/**
 * GET /search
 * Query params:
 *   q       - search query (required)
 *   type    - stock, crypto, forex, futures, index (optional)
 *   exchange- e.g. BINANCE, NASDAQ (optional)
 */
app.get('/search', async (req, res) => {
  const { q, type, exchange } = req.query;
  if (!q) {
    return res.status(400).json({ success: false, error: 'q is required' });
  }

  try {
    const results = await TradingView.search(
      q,
      type || undefined,
      exchange || undefined
    );
    res.json({ success: true, results });
  } catch (err) {
    console.error('TradingView search error:', err.message);
    res.status(503).json({ success: false, error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`TradingView bridge listening on port ${PORT}`);
});
