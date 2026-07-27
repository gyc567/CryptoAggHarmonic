import WebSocket from 'ws';

const ws = new WebSocket('wss://data.tradingview.com/socket.io/websocket?type=chart', {
  origin: 'https://www.tradingview.com',
  headers: {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
  },
});

ws.on('open', () => {
  console.log('WebSocket opened');
});

ws.on('message', (data) => {
  console.log('Message:', data.toString().slice(0, 200));
});

ws.on('error', (err) => {
  console.error('Error:', err.message);
});

ws.on('close', (code, reason) => {
  console.log('Close:', code, reason.toString());
});

setTimeout(() => {
  ws.close();
  process.exit(0);
}, 10000);
