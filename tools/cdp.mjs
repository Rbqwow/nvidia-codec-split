import fs from 'node:fs';

const port = Number(process.env.NV_CODEC_DEBUG_PORT || 9227);
const [action = 'targets', input] = process.argv.slice(2);
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
if (action === 'targets') {
  console.log(JSON.stringify(targets, null, 2));
  process.exit(0);
}
const target = targets.find(t => t.type === 'page' && t.url.includes('osc'))
  || targets.find(t => t.type === 'page');
if (!target) throw new Error('No overlay page available');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});
const command = action === 'evaluate'
  ? { method: 'Runtime.evaluate', params: {
      expression: fs.readFileSync(input, 'utf8'),
      awaitPromise: true, returnByValue: true, timeout: 45000,
    } }
  : JSON.parse(fs.readFileSync(input, 'utf8'));
try {
  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('CDP timeout')), 50000);
    socket.addEventListener('message', event => {
      const response = JSON.parse(event.data);
      if (response.id !== 1) return;
      clearTimeout(timer);
      response.error ? reject(new Error(JSON.stringify(response.error))) : resolve(response.result);
    });
    socket.send(JSON.stringify({ id: 1, ...command }));
  });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  if (action === 'evaluate') console.log(JSON.stringify(result.result.value, null, 2));
  else if (result.data && input.endsWith('screenshot.json')) {
    const dest = input.replace(/\.json$/, '.png');
    fs.writeFileSync(dest, Buffer.from(result.data, 'base64'));
    console.log(dest);
  } else console.log(JSON.stringify(result, null, 2));
} finally {
  socket.close();
}
