import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const owned = path.join(path.dirname(fileURLToPath(import.meta.url)), ".scratch");
export const fixture = process.env.PI_REMOTE_FIXTURE ?? owned;
assert.ok([owned, "/tmp/opencode/pi-remote-projects"].includes(fixture), "Unapproved test fixture path");
assert.equal(fs.realpathSync(fixture), fixture, "Fixture must not have symlink ancestry");
const stat = fs.statSync(fixture);
assert.equal(stat.uid, process.getuid());
assert.equal(stat.mode & 0o022, 0);
assert.equal(fs.readFileSync(path.join(fixture, ".fixture-owner"), "utf8"), "pi-remote-projects-public-test-fixture-v1\n");
