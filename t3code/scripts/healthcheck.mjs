import net from 'node:net';

// TCP liveness only: no readiness, auth, provider or acceptance assertion.
async function main() {
  const value = process.env.T3CODE_PORT ?? '';
  if (!/^[1-9][0-9]{0,4}$/.test(value) || Number(value) > 65535) {
    process.exitCode = 1;
    return;
  }
  const alive = await new Promise((resolve) => {
    const socket = net.createConnection({ host: '127.0.0.1', port: Number(value) });
    const finish = (result) => { socket.destroy(); resolve(result); };
    socket.setTimeout(2000);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
  });
  process.exitCode = alive ? 0 : 1;
}

await main();
