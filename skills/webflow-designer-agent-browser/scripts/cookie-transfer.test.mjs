import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createCipheriv, pbkdf2Sync } from "node:crypto";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, it } from "node:test";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

import { DatabaseSync } from "node:sqlite";
import {
  buildCdpCookieParams,
  decryptChromeCookieValue,
  injectCookiesIntoPage,
  readCookiesFromDatabase,
  snapshotCookieDatabase,
  validateCookieTransferPolicy,
} from "./cookie-transfer.mjs";

const temporaryDirectories = [];
const execFileAsync = promisify(execFile);
const secret = "synthetic Chrome Safe Storage secret";

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

function encrypted(value) {
  const key = pbkdf2Sync(secret, "saltysalt", 1003, 16, "sha1");
  const cipher = createCipheriv("aes-128-cbc", key, Buffer.alloc(16, 0x20));
  return Buffer.concat([Buffer.from("v10"), cipher.update(value, "utf8"), cipher.final()]);
}

function policy(enabled = true) {
  return {
    version: 1,
    cookieTransfer: { enabled, allowedDomains: ["webflow.com", "wfdev.io"] },
  };
}

describe("hardened cookie transfer", () => {
  it("decrypts Chrome v10 and v11 values without exposing the secret in output", () => {
    assert.equal(decryptChromeCookieValue(encrypted("cookie-value"), secret), "cookie-value");
    assert.equal(decryptChromeCookieValue(Buffer.from("plain-value"), secret), "plain-value");
  });

  it("rejects disabled policy, wildcards, and URL-shaped domains", () => {
    assert.throws(() => validateCookieTransferPolicy(policy(false)), /disabled/);
    assert.throws(
      () => validateCookieTransferPolicy({ ...policy(), cookieTransfer: { enabled: true, allowedDomains: ["*.webflow.com"] } }),
      /exact hostnames/,
    );
    assert.throws(
      () => validateCookieTransferPolicy({ ...policy(), cookieTransfer: { enabled: true, allowedDomains: ["https://webflow.com"] } }),
      /exact hostnames/,
    );
  });

  it("reads only allowed, unexpired cookies and preserves host-only/domain semantics", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "cookie-transfer-test-"));
    temporaryDirectories.push(directory);
    const databasePath = path.join(directory, "Cookies");
    const database = new DatabaseSync(databasePath);
    database.exec(`CREATE TABLE cookies (
      creation_utc INTEGER,
      host_key TEXT,
      name TEXT,
      value TEXT,
      path TEXT,
      expires_utc INTEGER,
      is_secure INTEGER,
      is_httponly INTEGER,
      encrypted_value BLOB,
      samesite INTEGER,
      last_update_utc INTEGER,
      partition_key TEXT
    )`);
    const insert = database.prepare(`INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`);
    const future = 11644473600000000 + (Date.now() / 1000 + 3600) * 1_000_000;
    insert.run(1, "design.wfdev.io", "host", "", "/", future, 1, 1, encrypted("host-value"), 2, 2, "");
    insert.run(1, ".webflow.com", "domain", "domain-value", "/app", future, 1, 0, Buffer.alloc(0), 3, 3, "");
    insert.run(1, "example.com", "outside", "outside", "/", future, 1, 1, Buffer.alloc(0), 0, 4, "");
    insert.run(1, "design.wfdev.io", "expired", "expired", "/", 1, 1, 1, Buffer.alloc(0), 0, 5, "");
    insert.run(1, "design.wfdev.io", "partitioned", "partitioned", "/", future, 1, 1, Buffer.alloc(0), 0, 6, "https://top.example");
    database.close();

    const records = readCookiesFromDatabase({
      databasePath,
      allowedDomains: ["webflow.com", "wfdev.io"],
      safeStorageSecret: secret,
    });
    assert.deepEqual(records.cookies.map(({ name, value }) => ({ name, value })), [
      { name: "host", value: "host-value" },
      { name: "domain", value: "domain-value" },
    ]);
    assert.equal(records.skippedDomain, 1);
    assert.equal(records.skippedExpired, 1);
    assert.equal(records.skippedPartitioned, 1);
    assert.deepEqual(buildCdpCookieParams(records.cookies).map((cookie) => ({
      name: cookie.name,
      domain: cookie.domain,
      url: cookie.url,
      sameSite: cookie.sameSite,
    })), [
      { name: "host", domain: undefined, url: "https://design.wfdev.io/", sameSite: "Lax" },
      { name: "domain", domain: ".webflow.com", url: undefined, sameSite: "Strict" },
    ]);
  });

  it("snapshots the database and sidecars without mutating the source", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "cookie-snapshot-test-"));
    temporaryDirectories.push(directory);
    const source = path.join(directory, "Cookies");
    const database = new DatabaseSync(source);
    database.exec("CREATE TABLE cookies (host_key TEXT, name TEXT, path TEXT, value TEXT, encrypted_value BLOB)");
    database.close();
    const snapshot = snapshotCookieDatabase(source);
    assert.notEqual(snapshot.databasePath, source);
    assert.equal(snapshot.directory.startsWith(os.tmpdir()), true);
    await rm(snapshot.directory, { recursive: true, force: true });
  });

  it("attaches to a dedicated page target before calling Network.setCookies", async () => {
    const calls = [];
    const client = {
      async send(method, params, sessionId) {
        calls.push({method, params, sessionId});
        if (method === "Target.getTargets") {
          return {targetInfos: [{targetId: "page-1", type: "page"}]};
        }
        if (method === "Target.attachToTarget") return {sessionId: "session-1"};
        return {};
      },
    };
    await injectCookiesIntoPage(client, [{name: "session", value: "redacted"}]);
    assert.deepEqual(calls.map(({method}) => method), [
      "Target.getTargets",
      "Target.attachToTarget",
      "Network.setCookies",
      "Target.detachFromTarget",
    ]);
    assert.equal(calls[2].sessionId, "session-1");
  });

  it("emits count-only CLI output without cookie values", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "cookie-cli-test-"));
    temporaryDirectories.push(directory);
    const databasePath = path.join(directory, "Cookies");
    const database = new DatabaseSync(databasePath);
    database.exec(`CREATE TABLE cookies (
      creation_utc INTEGER,
      host_key TEXT,
      name TEXT,
      value TEXT,
      path TEXT,
      expires_utc INTEGER,
      is_secure INTEGER,
      is_httponly INTEGER,
      encrypted_value BLOB
    )`);
    database.prepare("INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)").run(
      1,
      "design.wfdev.io",
      "session",
      "super-secret-cookie-value",
      "/",
      0,
      1,
      1,
      Buffer.alloc(0),
    );
    database.close();
    const policyPath = path.join(directory, "policy.json");
    await writeFile(policyPath, JSON.stringify(policy()));
    const scriptPath = fileURLToPath(new URL("./cookie-transfer.mjs", import.meta.url));
    const {stdout} = await execFileAsync(process.execPath, [
      scriptPath,
      "--source-db",
      databasePath,
      "--cdp-endpoint",
      "http://127.0.0.1:9333",
      "--policy",
      policyPath,
      "--dry-run",
    ]);
    assert.match(stdout, /eligible/);
    assert.doesNotMatch(stdout, /super-secret-cookie-value/);
  });
});
