// Copy only the owned fixture; never launch OpenCode or read real session data.
import { cp, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";

const root = await mkdtemp(path.join(tmpdir(), "session-title-v2-"));
try {
  const config = path.join(root, "config");
  const home = path.join(root, "home");
  await mkdir(config);
  await mkdir(home);
  await cp(new URL("./", import.meta.url), path.join(config, "tui-plugins"), { recursive: true });
  await cp(new URL("../cli.json", import.meta.url), path.join(config, "cli.json"));
  const env = {
    PATH: process.env.PATH,
    HOME: home,
    TMPDIR: root,
    XDG_CONFIG_HOME: path.join(home, "config"),
    XDG_CACHE_HOME: path.join(home, "cache"),
    XDG_DATA_HOME: path.join(home, "data"),
    XDG_STATE_HOME: path.join(home, "state"),
    npm_config_cache: path.join(root, "npm-cache"),
    npm_config_userconfig: path.join(root, "empty-user-npmrc"),
    npm_config_globalconfig: path.join(root, "empty-global-npmrc"),
  };
  for (const args of [
    ["--check", "tui-plugins/session-title.mjs"],
    ["--check", "tui-plugins/session-title/tui.js"],
    ["--test", "tui-plugins/session-title.test.mjs"],
  ]) {
    const result = spawnSync(process.execPath, args, { cwd: config, env, stdio: "inherit", timeout: 30_000 });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      process.exitCode = result.status ?? 1;
      break;
    }
  }
  if (!process.exitCode && process.argv.includes("--runtime")) {
    // Opt-in network check; no CLI binary, lifecycle scripts, or global installs.
    const installed = spawnSync("npm", [
      "install", "--ignore-scripts", "--no-save", "--package-lock=false", "--legacy-peer-deps",
      "--no-audit", "--no-fund", "--registry=https://registry.npmjs.org",
      "@opencode/plugin@2.0.32", "@opentui/solid@0.5.17", "solid-js@1.9.15",
    ], { cwd: config, env, stdio: "inherit", timeout: 180_000 });
    if (installed.error) throw installed.error;
    if (installed.status !== 0) throw new Error(`Isolated npm install failed: ${installed.status}`);
    await writeFile(path.join(config, "smoke.mjs"), `
      import assert from "node:assert/strict";
      import path from "node:path";
      import { Host } from "@opencode/plugin/host";
      import { jsx } from "@opentui/solid/jsx-runtime";
      assert.equal(typeof jsx, "function");
      const entry = Host.resolve({ directory: path.resolve("tui-plugins/session-title") });
      assert.ok(entry.tui?.endsWith("/session-title/tui.js"));
      assert.equal(entry.server, undefined);
      const { default: plugin } = await Host.load(entry.tui);
      assert.equal(plugin.id, "local.session-title");
      assert.equal(typeof plugin.setup, "function");
      let claim;
      const cleanup = () => {};
      assert.equal(plugin.setup({ ui: { slot(value) { claim = value; return cleanup; } } }), cleanup);
      assert.equal(claim.append, "prompt.footer.status");
      console.log("V2 2.0.32 Host.resolve/load + OpenTUI 0.5.17 real import/setup: PASS");
    `);
    const smoke = spawnSync(process.execPath, ["smoke.mjs"], { cwd: config, env, stdio: "inherit", timeout: 30_000 });
    if (smoke.error) throw smoke.error;
    process.exitCode = smoke.status ?? 1;
  }
} finally {
  await rm(root, { recursive: true, force: true });
}
