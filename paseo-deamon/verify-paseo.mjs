// Layout verified against Paseo 0.12.0, gitHead cafe4b01c8522ff39560241c5deb01427dc8dc5b:
// packages/server/{package.json,tsconfig.server.json} (rootDir src, outDir dist/server).
import { readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export function validatePaseo(root, expected) {
  if (!/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(expected)) {
    throw new Error("Exact stable PASEO_VERSION required");
  }
  const [major, minor] = expected.split(".").map(Number);
  if (major === 0 && minor < 12) {
    throw new Error("Paseo >=0.12.0 required for the native OpenCode V2 provider");
  }
  for (const name of ["cli", "server"]) {
    const pkg = JSON.parse(readFileSync(resolve(root, `@getpaseo/${name}/package.json`), "utf8"));
    if (pkg.name !== `@getpaseo/${name}` || pkg.version !== expected) {
      throw new Error(`Paseo ${name} does not match PASEO_VERSION`);
    }
    if (name === "server") {
      const client = pkg.dependencies?.["@opencode/client"];
      // Current upstream pins an exact client. Fail closed on packaging/range drift.
      if (typeof client !== "string" || !/^2\.\d+\.\d+$/.test(client)
          || (Number(client.split(".")[1]) === 0 && Number(client.split(".")[2]) < 10)) {
        throw new Error("Paseo server must declare an exact @opencode/client >=2.0.10 <3 dependency");
      }
    }
  }
  for (const file of [
    "provider-registry.js",
    "providers/opencode/runtime-client.js",
    "providers/opencode/v2/agent.js",
    "providers/opencode/v2/runtime.js",
  ]) {
    const path = resolve(root, "@getpaseo/server/dist/server/server/agent", file);
    if (!statSync(path).isFile()) throw new Error(`Missing Paseo V2 provider module: ${path}`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  validatePaseo("/usr/local/lib/node_modules", process.argv[2]);
}
