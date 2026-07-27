# TradingView Data Bridge

Node.js HTTP bridge that wraps [`@mathieuc/tradingview`](https://github.com/Mathieu2301/TradingView-API) so the Python backend can fetch real-time candles from TradingView.

## Why a separate service?

The pyharmonics-gpt backend is Python, but the TradingView API library is Node.js. Rather than re-implementing TradingView's WebSocket protocol in Python, we run a tiny Node bridge and call it from Python over HTTP.

## Run locally

```bash
cd tradingview-bridge
npm install
npm start
```

Default port: `5002`. Health check: `http://127.0.0.1:5002/health`.

## Endpoints

- `GET /health` — bridge status and WebSocket connection state
- `GET /candles?symbol=BTCUSDT&interval=4h&limit=500&market=binance` — OHLCV candles
- `GET /search?q=AAPL` — symbol search

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PORT` | `5002` | HTTP port |
| `TRADINGVIEW_DEBUG` | `0` | Set to `1` to enable verbose WebSocket logs |

## Notes

- TradingView WebSocket may be blocked in some network environments (e.g. mainland China). When the bridge cannot connect, the Python backend automatically falls back to Binance/Yahoo.
- Set `USE_TRADINGVIEW=false` in the backend environment to disable TradingView priority.
