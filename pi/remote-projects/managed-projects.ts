import { readFileSync } from "node:fs";
import { isIP } from "node:net";
import { posix } from "node:path";

export interface ProjectEntry {
  ref: string;
  label: string;
  address: string;
  port: number;
  user: string;
  cwd: string;
  identity_file: string;
  host_key_sha256: string;
  environment?: string;
  host_key?: string;
  workspace_name?: string;
}

const fields = ["ref", "label", "address", "user", "cwd", "identity_file", "host_key_sha256"] as const;
const extras = ["environment", "host_key", "workspace_name"] as const;
const canonicalRef = /^[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*$/;
const text = (value: unknown): value is string =>
  typeof value === "string" && value.trim() === value && value.length > 0 && !/[\x00-\x1f\x7f-\x9f]/.test(value);
const canonicalPath = (value: string): boolean =>
  value.startsWith("/") && posix.normalize(value) === value && (value === "/" || !value.endsWith("/"));

/** Read fresh on each use. Deployment must protect this file AND its ancestry
 * from service-user writes; metadata here is public, never private key content. */
export function loadProjectCatalog(path: string): ProjectEntry[] {
  if (!text(path) || !canonicalPath(path)) throw new Error("Invalid PI_PROJECT_CATALOG path");
  const root = JSON.parse(readFileSync(path, "utf8"));
  if (!root || !Array.isArray(root.projects)) throw new Error("Catalog must contain a projects array");
  const seen = new Set<string>();
  return root.projects.map((entry: any) => {
    if (!entry || fields.some((key) => !text(entry[key])) ||
        Object.keys(entry).some((key) => ![...fields, ...extras, "port"].includes(key as any)) ||
        extras.some((key) => entry[key] !== undefined && !text(entry[key])) ||
        !canonicalRef.test(entry.ref) ||
        !/^[a-z_][a-z0-9_-]*\$?$/.test(entry.user) ||
        !(isIP(entry.address) || (entry.address.length <= 253 && entry.address.split(".").every(
          (label: string) => /^(?=.{1,63}$)[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$/.test(label)))) ||
        !Number.isInteger(entry.port) || entry.port < 1 || entry.port > 65535 ||
        !canonicalPath(entry.cwd) || !canonicalPath(entry.identity_file) ||
        !/^[a-fA-F0-9]{64}$/.test(entry.host_key_sha256) || seen.has(entry.ref)) {
      throw new Error("Invalid or duplicate managed project entry");
    }
    seen.add(entry.ref);
    // Stable order makes comparisons independent of JSON object key ordering.
    return Object.freeze(Object.fromEntries(
      [...fields, "port", ...extras].filter((key) => entry[key] !== undefined).map((key) => [key, entry[key]]),
    )) as unknown as ProjectEntry;
  });
}

/** One instance per extension factory. No endpoint, credential or global cache. */
export class ManagedProjects {
  remoteIntent = false;
  projectRef: string | undefined;
  private selected: ProjectEntry | undefined;
  constructor(readonly path: string) {}

  begin(ref?: string): void {
    // Record intent without authorizing: validation/restore can still fail.
    this.remoteIntent = true;
    this.projectRef = typeof ref === "string" && canonicalRef.test(ref) ? ref : undefined;
    this.selected = undefined;
  }

  select(ref: string): ProjectEntry {
    this.begin(ref);
    const entry = loadProjectCatalog(this.path).find((item) => item.ref === ref);
    if (!entry) throw new Error("Project is not authorized; select an exact catalog reference");
    this.selected = entry;
    return entry;
  }

  current(): ProjectEntry {
    const entry = loadProjectCatalog(this.path).find((item) => item.ref === this.projectRef);
    if (!this.remoteIntent || !this.selected || !entry || JSON.stringify(entry) !== JSON.stringify(this.selected)) {
      throw new Error("Managed project missing, revoked or changed; explicitly reselect it");
    }
    return entry;
  }

  local(): void {
    this.remoteIntent = false;
    this.projectRef = undefined;
    this.selected = undefined;
  }
}
