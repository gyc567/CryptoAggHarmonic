import TradingView from '@mathieuc/tradingview';

const client = new TradingView.Client();
const chart = new client.Session.Chart();

chart.onError((...err) => {
  console.error('Chart error:', ...err);
});

chart.onSymbolLoaded(() => {
  console.log('Symbol loaded:', chart.infos.description);
});

chart.onUpdate(() => {
  console.log('Update, periods:', chart.periods ? chart.periods.length : 0);
  if (chart.periods && chart.periods.length > 0) {
    console.log('First period:', chart.periods[0]);
    console.log('Last period:', chart.periods[chart.periods.length - 1]);
    chart.delete();
    client.end();
    process.exit(0);
  }
});

chart.setMarket('BINANCE:BTCUSDT', {
  timeframe: '240',
  range: 10,
});

setTimeout(() => {
  console.log('Timeout');
  chart.delete();
  client.end();
  process.exit(1);
}, 15000);
