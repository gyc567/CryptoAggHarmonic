export function getSymbols(market: string): string[] {
  if (market === "binance") {
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "MATICUSDT", "DOTUSDT"];
  }
  return ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "AMD", "NFLX", "CRM"];
}
