import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validatePaseo } from "../verify-paseo.mjs";

function fixture(t, version = "0.12.0") {
  const root = mkdtempSync(join(dirname(fileURLToPath(import.meta.url)), ".paseo-fixture-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const name of ["cli", "server"]) {
    mkdirSync(join(root, `@getpaseo/${name}`), { recursive: true });
    writeFileSync(join(root, `@getpaseo/${name}/package.json`), JSON.stringify({
      name: `@getpaseo/${name}`, version, dependencies: { "@opencode/client": "2.0.10" },
    }));
  }
  for (const file of ["provider-registry.js", "providers/opencode/runtime-client.js",
    "providers/opencode/v2/agent.js", "providers/opencode/v2/runtime.js"]) {
    const path = join(root, "@getpaseo/server/dist/server/server/agent", file);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "export {};\n");
  }
  return root;
}

test("accepts exact 0.12.0 packages with compiled V2 provider layout", (t) => {
  assert.doesNotThrow(() => validatePaseo(fixture(t), "0.12.0"));
});

for (const version of ["0.8.0", "0.11.99"]) {
  test(`rejects older Paseo ${version} even with V2-shaped assets`, (t) => {
    assert.throws(() => validatePaseo(fixture(t, version), version), />=0.12.0/);
  });
}

test("rejects floating/prerelease version inputs", (t) => {
  const root = fixture(t);
  for (const version of ["latest", "0.12.0-beta.1", "v0.12.0"]) {
    assert.throws(() => validatePaseo(root, version), /Exact stable/);
  }
});

test("rejects CLI/server version mismatch", (t) => {
  assert.throws(() => validatePaseo(fixture(t), "0.12.1"), /does not match/);
});

test("rejects missing, old or unreviewed client dependency", (t) => {
  const root = fixture(t);
  const path = join(root, "@getpaseo/server/package.json");
  const pkg = JSON.parse(readFileSync(path, "utf8"));
  for (const client of [undefined, "2.0.9", "^2.0.10", "3.0.0"]) {
    pkg.dependencies = client ? { "@opencode/client": client } : {};
    writeFileSync(path, JSON.stringify(pkg));
    assert.throws(() => validatePaseo(root, "0.12.0"), /@opencode\/client/);
  }
});

for (const module of ["runtime-client.js", "v2/agent.js", "v2/runtime.js"]) {
  test(`rejects missing compiled ${module}`, (t) => {
    const root = fixture(t);
    rmSync(join(root, "@getpaseo/server/dist/server/server/agent/providers/opencode", module));
    assert.throws(() => validatePaseo(root, "0.12.0"), /ENOENT/);
  });
}

test("Docker build invokes the admitted validator", () => {
  const root = new URL("../", import.meta.url);
  assert.match(readFileSync(new URL("Dockerfile", root), "utf8"),
    /RUN node \/opt\/paseo-component\/verify-paseo\.mjs "\$PASEO_VERSION"/);
  assert.match(readFileSync(new URL("Dockerfile.dockerignore", root), "utf8"),
    /!paseo-deamon\/verify-paseo\.mjs/);
});
