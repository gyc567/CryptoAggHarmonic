import WebSocket from 'ws';

for (const server of ['data', 'prodata', 'widgetdata']) {
  const ws = new WebSocket(`wss://${server}.tradingview.com/socket.io/websocket?type=chart`, {
    origin: 'https://www.tradingview.com',
    headers: {
      'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    },
  });

  ws.on('open', () => console.log(`${server}: opened`));
  ws.on('message', (data) => console.log(`${server}: message`, data.toString().slice(0, 100)));
  ws.on('error', (err) => console.log(`${server}: error`, err.message));
  ws.on('close', (code, reason) => console.log(`${server}: close`, code, reason.toString()));
}

setTimeout(() => process.exit(0), 10000);
