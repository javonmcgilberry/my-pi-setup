#!/usr/bin/env node

import { readFileSync } from "node:fs";

function readObject(file) {
  let value;
  try {
    value = JSON.parse(readFileSync(file, "utf8"));
  } catch (error) {
    throw new Error(`Could not read JSON object from ${file}`, { cause: error });
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${file} must contain a JSON object`);
  }
  return value;
}

function merge(base, override) {
  const result = { ...base };
  for (const [key, value] of Object.entries(override)) {
    const current = result[key];
    result[key] =
      current &&
      value &&
      typeof current === "object" &&
      typeof value === "object" &&
      !Array.isArray(current) &&
      !Array.isArray(value)
        ? merge(current, value)
        : value;
  }
  return result;
}

const args = process.argv.slice(2);
const baseFile = args.shift();
let localFile;
if (args[0] && !args[0].startsWith("--")) localFile = args.shift();
let prewalkSource;
let existingFile;
const packageSources = [];
const managedKeys = new Set();
while (args.length > 0) {
  const option = args.shift();
  if (option === "--prewalk-source") prewalkSource = args.shift();
  else if (option === "--package-source") {
    packageSources.push({ tracked: args.shift(), local: args.shift() });
  }
  else if (option === "--existing-settings") existingFile = args.shift();
  else if (option === "--managed-key") managedKeys.add(args.shift());
  else throw new Error(`Unknown option: ${option}`);
}
if (
  !baseFile ||
  (process.argv.includes("--prewalk-source") && !prewalkSource) ||
  packageSources.some(({ tracked, local }) => !tracked || !local) ||
  (process.argv.includes("--existing-settings") && !existingFile) ||
  [...managedKeys].some((key) => !key)
) {
  throw new Error(
    "Usage: render-settings.mjs <settings.json> [settings.local.json] [--existing-settings <path>] [--managed-key <key>]... [--prewalk-source <path>] [--package-source <tracked> <local>]...",
  );
}

const base = readObject(baseFile);
let rendered = base;
let local;

if (localFile) {
  local = readObject(localFile);
  const allowed = new Set(["settings"]);
  const unknown = Object.keys(local).filter((key) => !allowed.has(key));
  if (unknown.length > 0) {
    throw new Error(`Unknown local settings keys: ${unknown.join(", ")}`);
  }

  if (local.settings !== undefined) {
    if (!local.settings || typeof local.settings !== "object" || Array.isArray(local.settings)) {
      throw new Error("settings.local.json settings must be a JSON object");
    }
    rendered = merge(rendered, local.settings);
  }
}

if (existingFile) {
  const existing = readObject(existingFile);
  const preferences = Object.fromEntries(
    Object.entries(existing).filter(([key]) => !managedKeys.has(key)),
  );
  rendered = { ...rendered, ...preferences };
}

if (prewalkSource) {
  if (!Array.isArray(rendered.packages)) {
    throw new Error("Tracked settings must contain a packages array before selecting local Prewalk");
  }
  const trackedPrewalk = "git:github.com/javonmcgilberry/pi-prewalk";
  const packages = [...rendered.packages];
  const index = packages.indexOf(trackedPrewalk);
  if (index === -1) throw new Error(`Cannot select local Prewalk without ${trackedPrewalk}`);
  packages[index] = prewalkSource;
  rendered = { ...rendered, packages };
}

for (const { tracked, local } of packageSources) {
  if (!Array.isArray(rendered.packages)) {
    throw new Error("Tracked settings must contain a packages array before selecting local packages");
  }
  const packages = [...rendered.packages];
  const index = packages.indexOf(tracked);
  if (index === -1) throw new Error(`Cannot select local package without ${tracked}`);
  packages[index] = local;
  rendered = { ...rendered, packages };
}

process.stdout.write(`${JSON.stringify(rendered, null, 2)}\n`);
