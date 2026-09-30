// Used by image healthchecks and launcher readiness. Credentials stay in env.
const url = 'http://127.0.0.1:4096/global/health';

export async function checkHealth() {
  const password = process.env.OPENCODE_SERVER_PASSWORD;
  const headers = password ? {
    Authorization: `Basic ${Buffer.from(`${process.env.OPENCODE_SERVER_USERNAME || 'opencode'}:${password}`).toString('base64')}`,
  } : {};
  try {
    const response = await fetch(url, { headers, signal: AbortSignal.timeout(2000) });
    return response.ok && (await response.json()).healthy === true;
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
