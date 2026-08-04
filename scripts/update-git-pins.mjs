#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repoDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const settingsPath = join(repoDir, "settings.json");
const localPaths = [
  join(repoDir, "settings.local.json"),
  join(repoDir, "settings.local.example.json"),
];
const pins = [
  { repository: "javonmcgilberry/context-mode", branch: "main" },
];

const settings = JSON.parse(readFileSync(settingsPath, "utf8"));
const replacements = [];
for (const pin of pins) {
  const output = execFileSync(
    "git",
    ["ls-remote", `https://github.com/${pin.repository}.git`, `refs/heads/${pin.branch}`],
    { encoding: "utf8" },
  ).trim();
  const sha = output.split(/\s+/)[0];
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error(`Unable to resolve ${pin.repository}#${pin.branch}`);
  const prefix = `git:github.com/${pin.repository}@`;
  const index = settings.packages.findIndex((entry) => typeof entry === "string" && entry.startsWith(prefix));
  if (index < 0) throw new Error(`Missing tracked package pin for ${pin.repository}`);
  const previous = settings.packages[index];
  const next = `${prefix}${sha}`;
  settings.packages[index] = next;
  replacements.push([previous, next]);
}
writeFileSync(settingsPath, `${JSON.stringify(settings, null, 2)}\n`);

for (const localPath of localPaths) {
  if (existsSync(localPath)) {
    const local = JSON.parse(readFileSync(localPath, "utf8"));
    if (local.packageReplacements) {
      for (const [previous, next] of replacements) {
        if (previous !== next && Object.hasOwn(local.packageReplacements, previous)) {
          local.packageReplacements[next] = local.packageReplacements[previous];
          delete local.packageReplacements[previous];
        }
      }
    }
    writeFileSync(localPath, `${JSON.stringify(local, null, 2)}\n`);
  }
}
