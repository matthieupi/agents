// Used by image healthchecks and launcher readiness. Credentials stay in env.
const port = process.argv.slice(2).find(argument => argument !== '--wait') ?? '4096';
if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) process.exit(1);
const url = `http://127.0.0.1:${port}/api/info`;

export async function checkHealth() {
  const password = process.env.OPENCODE_PASSWORD ?? process.env.OPENCODE_SERVER_PASSWORD;
  const headers = password ? {
    Authorization: `Basic ${Buffer.from(`opencode:${password}`).toString('base64')}`,
  } : {};
  try {
    const response = await fetch(url, { headers, signal: AbortSignal.timeout(2000) });
    if (!response.ok) return false;
    const info = await response.json();
    return typeof info?.version === 'string' && /^([2-9]|[1-9][0-9]+)\./.test(info.version);
  } catch {
    return false;
  }
}

export async function waitForHealth(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  do {
    if (await checkHealth()) return true;
    if (Date.now() >= deadline) return false;
    await new Promise(resolve => setTimeout(resolve, 500));
  } while (Date.now() < deadline);
  return false;
}

// The hard deadline also bounds stalled response bodies and startup failures.
const timeoutMs = process.argv.includes('--wait') ? 120000 : 3000;
const deadline = setTimeout(() => process.exit(1), timeoutMs);
const healthy = await waitForHealth(process.argv.includes('--wait') ? timeoutMs : 0);
clearTimeout(deadline);
process.exit(healthy ? 0 : 1);
