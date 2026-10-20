// Product-owned runtime configuration preload, before upstream server import.
// No installs, subprocesses, DB writes, secret generation or company/agent seed.
import { readFileSync, writeFileSync } from "node:fs";

function readSecret(name) {
  const value = readFileSync(`/run/secrets/${name}`, "utf8").trim();
  if (!/^[a-f0-9]{64}$/.test(value)) {
    throw new Error(`Invalid Paperclip service secret: ${name}`);
  }
  return value;
}

function configuration(env) {
  const publicUrl = new URL(env.PAPERCLIP_PUBLIC_URL);
  if (publicUrl.protocol !== "https:" || publicUrl.username || publicUrl.password ||
      publicUrl.port || publicUrl.pathname !== "/" || publicUrl.search || publicUrl.hash ||
      env.PAPERCLIP_ALLOWED_HOSTNAMES !== publicUrl.hostname ||
      env.PAPERCLIP_DEPLOYMENT_MODE !== "authenticated" ||
      env.PAPERCLIP_DEPLOYMENT_EXPOSURE !== "private" ||
      env.HEARTBEAT_SCHEDULER_ENABLED !== "false" ||
      env.PAPERCLIP_TELEMETRY_DISABLED !== "1" ||
      !/^[a-z][a-z0-9_]*$/.test(env.PAPERCLIP_DB_USER ?? "") ||
      !/^[a-z][a-z0-9_]*$/.test(env.PAPERCLIP_DB_NAME ?? "") ||
      !Number.isInteger(Number(env.PORT)) || Number(env.PORT) < 1024 || Number(env.PORT) > 65535 ||
      !["true", "false"].includes(env.PAPERCLIP_AUTH_DISABLE_SIGN_UP)) {
    throw new Error("Paperclip requires canonical private HTTPS base-service configuration");
  }
  return {
    $meta: { version: 1, updatedAt: new Date().toISOString(), source: "configure" },
    database: { mode: "postgres", backup: { enabled: false } },
    logging: { mode: "file", logDir: "/paperclip/logs" },
    server: {
      deploymentMode: "authenticated", exposure: "private", serveUi: true,
      host: env.HOST, port: Number(env.PORT), allowedHostnames: [publicUrl.hostname],
    },
    auth: {
      baseUrlMode: "explicit", publicBaseUrl: env.PAPERCLIP_PUBLIC_URL,
      disableSignUp: env.PAPERCLIP_AUTH_DISABLE_SIGN_UP === "true",
    },
    telemetry: { enabled: false },
    updates: { checkEnabled: false },
    storage: { provider: "local_disk", localDisk: { baseDir: "/paperclip/assets" } },
    secrets: {
      provider: "local_encrypted",
      strictMode: true,
      localEncrypted: { keyFilePath: "/run/secrets/master-key" },
    },
  };
}

const config = configuration(process.env);
process.env.BETTER_AUTH_SECRET = readSecret("better-auth-secret");
process.env.PAPERCLIP_TOOL_ACTION_SIGNING_SECRET = readSecret("tool-action-signing-secret");
// Validate the key eagerly rather than allowing upstream to create a new key
// for an existing database after an incomplete restore.
readSecret("master-key");
process.env.PAPERCLIP_SECRETS_MASTER_KEY_FILE = "/run/secrets/master-key";
process.env.DATABASE_URL = `postgresql://${encodeURIComponent(process.env.PAPERCLIP_DB_USER)}:${readSecret("postgres-password")}@postgres:5432/${encodeURIComponent(process.env.PAPERCLIP_DB_NAME)}`;
// This file is disposable private runtime config on a dedicated tmpfs, not
// persistent configuration migration. Secrets remain out of JSON and stdout.
writeFileSync(process.env.PAPERCLIP_CONFIG, `${JSON.stringify(config, null, 2)}\n`, {
  mode: 0o600,
});
