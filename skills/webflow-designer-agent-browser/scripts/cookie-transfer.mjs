#!/usr/bin/env node

import { copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync, statSync, chmodSync } from "node:fs";
import { createDecipheriv, pbkdf2Sync } from "node:crypto";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { DatabaseSync } from "node:sqlite";
import process from "node:process";

const CHROME_EPOCH_OFFSET_MICROSECONDS = 11644473600000000;
const COOKIE_DB_SIDECARS = ["", "-wal", "-shm", "-journal"];
const CDP_HOSTS = new Set(["127.0.0.1"]);

export class CookieTransferFailure extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "CookieTransferFailure";
    this.code = code;
  }
}

function assertRecord(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new CookieTransferFailure("invalid_policy", `${name} must be an object`);
  }
}

export function validateCookieTransferPolicy(policy) {
  assertRecord(policy, "policy");
  if (policy.version !== 1) {
    throw new CookieTransferFailure("invalid_policy", "policy version must be 1");
  }
  assertRecord(policy.cookieTransfer, "cookieTransfer");
  if (policy.cookieTransfer.enabled !== true) {
    throw new CookieTransferFailure("cookie_transfer_disabled", "cookie transfer is disabled by policy");
  }
  const domains = policy.cookieTransfer.allowedDomains;
  const normalizedDomains = Array.isArray(domains)
    ? domains.map((domain) => typeof domain === "string" ? domain.trim().toLowerCase().replace(/^\.+/, "") : domain)
    : domains;
  if (
    !Array.isArray(normalizedDomains) ||
    normalizedDomains.length === 0 ||
    normalizedDomains.some(
      (domain) =>
        typeof domain !== "string" ||
        domain === "" ||
        domain.includes("*") ||
        domain.includes("/") ||
        domain.includes(":") ||
        /[\s\u0000-\u001f]/.test(domain),
    )
  ) {
    throw new CookieTransferFailure(
      "invalid_cookie_domains",
      "cookieTransfer.allowedDomains must contain exact hostnames without wildcards or URLs",
    );
  }
  return [...new Set(normalizedDomains)];
}

function domainAllowed(hostKey, allowedDomains) {
  const host = hostKey.trim().toLowerCase().replace(/^\.+/, "");
  if (!host || host.includes("/") || host.includes(":")) return false;
  return allowedDomains.some((domain) => host === domain || host.endsWith(`.${domain}`));
}

function copyStats(path) {
  if (!existsSync(path)) return null;
  const stat = statSync(path);
  return `${stat.size}:${stat.mtimeMs}:${stat.ino}`;
}

/**
 * Make a stable, private snapshot of Cookies and its SQLite sidecars.
 * The source profile is never opened for writing and is never launched.
 */
export function snapshotCookieDatabase(sourceDatabase, retries = 3) {
  const source = resolve(sourceDatabase);
  if (!existsSync(source)) {
    throw new CookieTransferFailure("cookie_database_missing");
  }
  for (let attempt = 0; attempt < retries; attempt += 1) {
    const directory = mkdtempSync(join(tmpdir(), "webflow-cookie-transfer-"));
    chmodSync(directory, 0o700);
    const before = COOKIE_DB_SIDECARS.map((suffix) => copyStats(`${source}${suffix}`));
    try {
      for (const suffix of COOKIE_DB_SIDECARS) {
        const sourcePath = `${source}${suffix}`;
        if (existsSync(sourcePath)) copyFileSync(sourcePath, join(directory, `Cookies${suffix}`));
      }
      const after = COOKIE_DB_SIDECARS.map((suffix) => copyStats(`${source}${suffix}`));
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        rmSync(directory, { recursive: true, force: true });
        continue;
      }
      chmodSync(join(directory, "Cookies"), 0o600);
      return { directory, databasePath: join(directory, "Cookies") };
    } catch (error) {
      rmSync(directory, { recursive: true, force: true });
      if (error instanceof CookieTransferFailure) throw error;
      if (attempt === retries - 1) {
        throw new CookieTransferFailure("cookie_snapshot_failed");
      }
    }
  }
  throw new CookieTransferFailure("cookie_source_changed");
}

export function deriveChromeCookieKey(safeStorageSecret) {
  if (typeof safeStorageSecret !== "string" || safeStorageSecret.length === 0) {
    throw new CookieTransferFailure("keychain_unavailable");
  }
  // Chrome on macOS uses PBKDF2-HMAC-SHA1 with these fixed legacy parameters.
  return cryptoPbkdf2(safeStorageSecret, "saltysalt", 1003, 16);
}

function cryptoPbkdf2(secret, salt, iterations, keyLength) {
  // Kept in a small adapter so tests can exercise decryption without touching Keychain.
  return pbkdf2Sync(secret, salt, iterations, keyLength, "sha1");
}

export function decryptChromeCookieValue(encryptedValue, safeStorageSecret) {
  const encrypted = Buffer.from(encryptedValue ?? []);
  if (encrypted.length === 0) return "";
  const prefix = encrypted.subarray(0, 3).toString("ascii");
  if (encrypted.length < 3 || !prefix.startsWith("v")) {
    return encrypted.toString("utf8");
  }
  if (!["v10", "v11"].includes(prefix)) {
    throw new CookieTransferFailure("cookie_encryption_unsupported");
  }
  const key = deriveChromeCookieKey(safeStorageSecret);
  const decipher = createDecipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
  decipher.setAutoPadding(false);
  const plaintext = Buffer.concat([
    decipher.update(encrypted.subarray(3)),
    decipher.final(),
  ]);
  const padding = plaintext.at(-1);
  if (!padding || padding > 16 || plaintext.subarray(-padding).some((value) => value !== padding)) {
    throw new CookieTransferFailure("cookie_decryption_failed");
  }
  return plaintext.subarray(0, plaintext.length - padding).toString("utf8");
}

function readSafeStorageSecret() {
  if (process.platform !== "darwin") {
    throw new CookieTransferFailure("keychain_platform_unsupported");
  }
  for (const args of [
    ["find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
    ["find-generic-password", "-w", "-s", "Chrome Safe Storage"],
  ]) {
    try {
      const secret = execFileSync("/usr/bin/security", args, {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      }).trim();
      if (secret) return secret;
    } catch {
      // The account form differs across Chrome installations; try the next safe form.
    }
  }
  throw new CookieTransferFailure("keychain_item_missing");
}

function chromeTimestampToUnixSeconds(value) {
  if (typeof value === "string" && /^\d+$/.test(value)) value = BigInt(value);
  if (typeof value === "bigint") {
    if (value <= 0n) return undefined;
    return Number(value - BigInt(CHROME_EPOCH_OFFSET_MICROSECONDS)) / 1_000_000;
  }
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return undefined;
  return (value - CHROME_EPOCH_OFFSET_MICROSECONDS) / 1_000_000;
}

function integerEquals(value, expected) {
  return value === expected || value === BigInt(expected);
}

function timestampForOrdering(value) {
  if (typeof value === "bigint") return value;
  if (typeof value === "string" && /^\d+$/.test(value)) return BigInt(value);
  if (typeof value === "number" && Number.isFinite(value)) return BigInt(Math.trunc(value));
  return 0n;
}

function tableColumns(database) {
  return new Set(database.prepare("PRAGMA table_info(cookies)").all().map((row) => row.name));
}

function cookieRows(database) {
  const columns = tableColumns(database);
  if (!columns.has("host_key") || !columns.has("name") || !columns.has("path")) {
    throw new CookieTransferFailure("cookie_schema_unsupported");
  }
  const required = ["creation_utc", "value", "expires_utc", "is_secure", "is_httponly", "encrypted_value"];
  const selected = ["host_key", "name", "path", ...required.filter((column) => columns.has(column))];
  for (const column of ["samesite", "source_scheme", "source_port", "last_update_utc", "partition_key", "partition_key_opaque"]) {
    if (columns.has(column)) selected.push(column);
  }
  const integerColumns = new Set(["creation_utc", "expires_utc", "last_update_utc"]);
  const selection = selected.map((column) =>
    integerColumns.has(column) ? `CAST(${column} AS TEXT) AS ${column}` : column,
  );
  return database.prepare(`SELECT ${selection.join(", ")} FROM cookies`).all();
}

function rowValue(row, key, fallback) {
  return Object.prototype.hasOwnProperty.call(row, key) ? row[key] : fallback;
}

function sameSiteValue(value) {
  if (integerEquals(value, 1)) return "None";
  if (integerEquals(value, 2)) return "Lax";
  if (integerEquals(value, 3)) return "Strict";
  return undefined;
}

export function readCookiesFromDatabase({
  databasePath,
  allowedDomains,
  safeStorageSecret,
  nowSeconds = Date.now() / 1000,
  keychainReader = readSafeStorageSecret,
}) {
  const domains = allowedDomains.map((domain) => domain.toLowerCase().replace(/^\.+/, ""));
  const database = new DatabaseSync(databasePath, { readOnly: true });
  const result = {
    cookies: [],
    skippedExpired: 0,
    skippedDomain: 0,
    skippedPartitioned: 0,
    skippedInvalid: 0,
  };
  try {
    const rows = cookieRows(database);
    let secret = safeStorageSecret;
    for (const row of rows) {
      const hostKey = typeof row.host_key === "string" ? row.host_key : "";
      if (!domainAllowed(hostKey, domains)) {
        result.skippedDomain += 1;
        continue;
      }
      const partitionKey = rowValue(row, "partition_key", "");
      if (typeof partitionKey === "string" && partitionKey.length > 0) {
        result.skippedPartitioned += 1;
        continue;
      }
      const expires = chromeTimestampToUnixSeconds(rowValue(row, "expires_utc", 0));
      if (expires !== undefined && expires <= nowSeconds) {
        result.skippedExpired += 1;
        continue;
      }
      const encrypted = rowValue(row, "encrypted_value", Buffer.alloc(0));
      let value = typeof rowValue(row, "value", "") === "string" ? rowValue(row, "value", "") : "";
      if (Buffer.from(encrypted ?? []).length > 0) {
        if (secret === undefined) secret = keychainReader();
        value = decryptChromeCookieValue(encrypted, secret);
      }
      const name = typeof row.name === "string" ? row.name : "";
      const path = typeof row.path === "string" && row.path.startsWith("/") ? row.path : "/";
      if (!name || !hostKey || /[\u0000-\u001f]/.test(name) || /[\u0000-\u001f]/.test(value)) {
        result.skippedInvalid += 1;
        continue;
      }
      result.cookies.push({
        name,
        value,
        hostKey,
        path,
        secure: integerEquals(rowValue(row, "is_secure", 0), 1),
        httpOnly: integerEquals(rowValue(row, "is_httponly", 0), 1),
        sameSite: sameSiteValue(rowValue(row, "samesite", 0)),
        expires,
        lastUpdate: timestampForOrdering(rowValue(row, "last_update_utc", rowValue(row, "creation_utc", 0))),
      });
    }
  } finally {
    database.close();
  }
  const deduped = new Map();
  for (const cookie of result.cookies) {
    const key = `${cookie.name}\u0000${cookie.hostKey}\u0000${cookie.path}`;
    const existing = deduped.get(key);
    if (!existing || cookie.lastUpdate >= existing.lastUpdate) deduped.set(key, cookie);
  }
  result.cookies = [...deduped.values()];
  return result;
}

export function buildCdpCookieParams(cookies) {
  return cookies.map((cookie) => {
    const domain = cookie.hostKey.toLowerCase();
    const base = {
      name: cookie.name,
      value: cookie.value,
      path: cookie.path,
      secure: cookie.secure,
      httpOnly: cookie.httpOnly,
    };
    if (cookie.sameSite) base.sameSite = cookie.sameSite;
    if (cookie.expires !== undefined) base.expires = cookie.expires;
    if (domain.startsWith(".")) {
      return { ...base, domain };
    }
    return {
      ...base,
      url: `${cookie.secure ? "https" : "http"}://${domain}${cookie.path}`,
    };
  });
}

export async function connectCdp(endpoint) {
  const url = new URL(endpoint);
  if (url.protocol !== "http:" || !CDP_HOSTS.has(url.hostname)) {
    throw new CookieTransferFailure("cdp_loopback_required");
  }
  const response = await fetch(new URL("/json/version", url));
  if (!response.ok) throw new CookieTransferFailure("cdp_version_unavailable");
  const version = await response.json();
  if (typeof version.webSocketDebuggerUrl !== "string") {
    throw new CookieTransferFailure("cdp_websocket_unavailable");
  }
  const websocketUrl = new URL(version.webSocketDebuggerUrl);
  if (websocketUrl.protocol !== "ws:" || !CDP_HOSTS.has(websocketUrl.hostname)) {
    throw new CookieTransferFailure("cdp_websocket_loopback_required");
  }
  const socket = new WebSocket(websocketUrl.href);
  let nextId = 0;
  const pending = new Map();
  await new Promise((resolvePromise, rejectPromise) => {
    socket.addEventListener("open", resolvePromise, { once: true });
    socket.addEventListener("error", () => rejectPromise(new CookieTransferFailure("cdp_connection_failed")), { once: true });
  });
  socket.addEventListener("message", (event) => {
    try {
      const message = JSON.parse(event.data);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new CookieTransferFailure("cdp_command_failed"));
      else request.resolve(message.result ?? {});
    } catch {
      // Malformed CDP messages cannot satisfy a pending request.
    }
  });
  return {
    send(method, params = {}, sessionId) {
      const id = ++nextId;
      return new Promise((resolvePromise, rejectPromise) => {
        pending.set(id, { resolve: resolvePromise, reject: rejectPromise });
        socket.send(JSON.stringify({
          id,
          method,
          params,
          ...(sessionId ? { sessionId } : {}),
        }));
      });
    },
    close() {
      socket.close();
    },
  };
}

export async function injectCookiesIntoPage(client, cookies) {
  const targets = await client.send("Target.getTargets");
  let target = targets.targetInfos?.find((entry) => entry.type === "page");
  let createdTarget = false;
  if (!target) {
    const created = await client.send("Target.createTarget", { url: "about:blank" });
    target = { targetId: created.targetId };
    createdTarget = true;
  }
  const attached = await client.send("Target.attachToTarget", {
    targetId: target.targetId,
    flatten: true,
  });
  const sessionId = attached.sessionId;
  try {
    await client.send("Network.setCookies", { cookies }, sessionId);
  } finally {
    await client.send("Target.detachFromTarget", { sessionId }).catch(() => undefined);
    if (createdTarget) {
      await client.send("Target.closeTarget", { targetId: target.targetId }).catch(() => undefined);
    }
  }
}

export async function transferCookies({ databasePath, policy, cdpEndpoint, dryRun = false }) {
  const allowedDomains = validateCookieTransferPolicy(policy);
  const snapshot = snapshotCookieDatabase(databasePath);
  try {
    const records = readCookiesFromDatabase({
      databasePath: snapshot.databasePath,
      allowedDomains,
    });
    const cdpCookies = buildCdpCookieParams(records.cookies);
    if (!dryRun) {
      const client = await connectCdp(cdpEndpoint);
      try {
        await injectCookiesIntoPage(client, cdpCookies);
      } finally {
        client.close();
      }
    }
    return {
      status: dryRun ? "eligible" : "transferred",
      injectedCount: dryRun ? 0 : cdpCookies.length,
      eligibleCount: cdpCookies.length,
      skippedExpired: records.skippedExpired,
      skippedDomain: records.skippedDomain,
      skippedPartitioned: records.skippedPartitioned,
      skippedInvalid: records.skippedInvalid,
      allowedDomains,
    };
  } finally {
    rmSync(snapshot.directory, { recursive: true, force: true });
  }
}

function parseArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--dry-run") {
      values.dryRun = true;
      continue;
    }
    if (["--source-db", "--cdp-endpoint", "--policy"].includes(token)) {
      const value = argv[++index];
      if (!value) throw new CookieTransferFailure("argument_missing");
      values[token.slice(2).replaceAll("-", "_")] = value;
      continue;
    }
    throw new CookieTransferFailure("argument_unknown");
  }
  if (!values.source_db || !values.cdp_endpoint || !values.policy) {
    throw new CookieTransferFailure("argument_missing");
  }
  return values;
}

async function main() {
  try {
    const args = parseArgs(process.argv.slice(2));
    const policy = JSON.parse(readFileSync(args.policy, "utf8"));
    const result = await transferCookies({
      databasePath: args.source_db,
      policy,
      cdpEndpoint: args.cdp_endpoint,
      dryRun: args.dryRun,
    });
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    const failure = error instanceof CookieTransferFailure
      ? error
      : new CookieTransferFailure("cookie_transfer_failed");
    process.stdout.write(`${JSON.stringify({ status: "blocked", error: { code: failure.code } })}\n`);
    process.exitCode = 2;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) await main();
