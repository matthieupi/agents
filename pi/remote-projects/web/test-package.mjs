// Install 0.9.0 then replace it with our packed build in an owned scratch prefix.
// Only an ephemeral loopback test server; never a controller/global installation.
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createServer } from "node:net";
import { get } from "node:http";

const root = dirname(fileURLToPath(import.meta.url));
const prefix = mkdtempSync(join(root, ".scratch/package-test-"));
const artifact = join(root, ".scratch/out/agegr-pi-web-0.9.0-remote.1.tgz");
const install = (archive) => execFileSync("npm", ["install", "--prefix", prefix, "--ignore-scripts", "--no-audit", "--no-fund", archive], { stdio: "inherit" });
install(join(root, ".scratch/pi-web.tgz"));
const pkg = join(prefix, "node_modules/@agegr/pi-web");
assert.equal(JSON.parse(readFileSync(join(pkg, "package.json"))).version, "0.9.0");
install(artifact);
assert.equal(JSON.parse(readFileSync(join(pkg, "package.json"))).version, "0.9.0-remote.1");
execFileSync("npm", ["rebuild", "--prefix", prefix, "node-pty"], { stdio: "inherit" });
execFileSync(process.execPath, [join(pkg, "bin/prepare-terminal.js")]);

const home = join(prefix, "home"), control = join(home, "control");
mkdirSync(control, { recursive: true });
process.env.HOME = home;
process.env.PI_CODING_AGENT_DIR = join(home, ".pi/agent");
writeFileSync(join(control, "local-only.txt"), "LOCAL_ONLY_FIXTURE");
const sdk = await import(pathToFileURL(join(prefix, "node_modules/@earendil-works/pi-coding-agent/dist/index.js")));
function session(data) {
  const manager = sdk.SessionManager.create(control);
  manager.appendCustomEntry("pi-ssh-remote-project", data);
  manager.appendMessage({ role: "assistant", content: [], api: "openai-completions", provider: "fixture", model: "fixture",
    usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "stop", timestamp: Date.now() });
  return manager.getSessionId();
}
const remoteId = session({ version: 1, local: false, projectRef: "invalid-pending" });
const localId = session({ version: 1, local: true, projectRef: null });
const probe = createServer();
await new Promise((resolve) => probe.listen(0, "127.0.0.1", resolve));
const port = probe.address().port;
await new Promise((resolve) => probe.close(resolve));
const password = "public-test-fixture";
const server = spawn(process.execPath, [join(prefix, "node_modules/next/dist/bin/next"), "start", "-H", "127.0.0.1", "-p", String(port)],
  { cwd: pkg, env: { ...process.env, PI_WEB_PASSWORD: password }, stdio: ["ignore", "pipe", "pipe"] });
let logs = "";
server.stdout.on("data", (data) => { logs += data; });
server.stderr.on("data", (data) => { logs += data; });
const base = `http://127.0.0.1:${port}`;
const authorization = `Basic ${Buffer.from(`pi:${password}`).toString("base64")}`;
const request = (path, options = {}) => fetch(base + path, {
  ...options, headers: { authorization, ...options.headers }, signal: AbortSignal.timeout(10_000),
});
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { if ((await request("/api/home")).status === 200) { ready = true; break; } } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  assert.ok(ready, logs);
  assert.equal((await fetch(base + "/api/home")).status, 401);
  assert.equal((await request("/api/home", { headers: { authorization: "Basic invalid" } })).status, 401);
  assert.equal((await request("/api/home", { headers: { origin: "https://untrusted.example" } })).status, 403);
  // Node fetch normalizes Host; use a real explicit HTTP Host header here.
  const badHostStatus = await new Promise((resolve, reject) => {
    get(base + "/api/home", { headers: { host: "untrusted.example", authorization } }, (response) => {
      response.resume(); resolve(response.statusCode);
    }).on("error", reject);
  });
  assert.equal(badHostStatus, 403);
  assert.equal((await request("/")).status, 200);
  for (const id of [remoteId, localId]) {
    const response = await request(`/api/sessions/${id}/state`);
    assert.equal(response.status, 200);
    assert.equal((await response.json()).projectMode, id === remoteId ? "remote" : "local");
  }
  for (const route of ["files/x", "file-index", "git/status", "git/diff", "worktrees", "terminal/missing", "terminal/missing/events"]) {
    for (const id of [remoteId, "unknown", ""]) assert.equal((await request(`/api/${route}?sessionId=${id}`)).status, 409, route);
  }
  assert.equal((await request(`/api/terminal?sessionId=${remoteId}`, { method: "POST" })).status, 409);
  const files = `/api/files/${control.split("/").filter(Boolean).map(encodeURIComponent).join("/")}?type=list`;
  for (const suffix of ["", `&sessionId=${localId}`]) {
    const response = await request(files + suffix);
    assert.equal(response.status, 200);
    assert.ok((await response.json()).entries.some((entry) => entry.name === "local-only.txt"));
  }
  console.log("PASS: npm replacement 0.9.0 -> 0.9.0-remote.1; packed Next HTTP: Basic, host/origin, mode, local files and remote/unknown rejections");
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => server.once("exit", resolve));
  writeFileSync(join(prefix, "server.log"), logs);
}
