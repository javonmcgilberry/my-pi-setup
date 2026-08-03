#!/usr/bin/env node

import { readFileSync } from "node:fs";

function readObject(file) {
  const value = JSON.parse(readFileSync(file, "utf8"));
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

const [baseFile, localFile] = process.argv.slice(2);
if (!baseFile) throw new Error("Usage: render-settings.mjs <settings.json> [settings.local.json]");

const base = readObject(baseFile);
let rendered = base;

if (localFile) {
  const local = readObject(localFile);
  const allowed = new Set(["settings", "packageReplacements"]);
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

  if (local.packageReplacements !== undefined) {
    const replacements = local.packageReplacements;
    if (!replacements || typeof replacements !== "object" || Array.isArray(replacements)) {
      throw new Error("settings.local.json packageReplacements must be a JSON object");
    }
    if (!Array.isArray(rendered.packages)) {
      throw new Error("Tracked settings must contain a packages array before applying replacements");
    }
    const packages = [...rendered.packages];
    for (const [source, replacement] of Object.entries(replacements)) {
      if (typeof replacement !== "string" || replacement.length === 0) {
        throw new Error(`Replacement for ${source} must be a non-empty string`);
      }
      const index = packages.indexOf(source);
      if (index === -1) throw new Error(`Cannot replace missing package source: ${source}`);
      packages[index] = replacement;
    }
    rendered = { ...rendered, packages };
  }
}

process.stdout.write(`${JSON.stringify(rendered, null, 2)}\n`);
