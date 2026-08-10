#!/usr/bin/env node

import { existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const MANIFEST_VERSION = 1;
export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const ROOTS = new Set(["pi", "shared", "commands", "macosLaunchAgents"]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertRecord(value, label) {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  return value;
}

function assertRelativePath(value, label, { allowTrailingSlash = false } = {}) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty relative path`);
  }
  const path = allowTrailingSlash ? value.replace(/\/+$/, "") : value;
  if (
    path.length === 0 ||
    path.startsWith("/") ||
    /^[A-Za-z]:[\\/]/.test(path) ||
    path.includes("\\") ||
    path.includes("//") ||
    /[\u0000-\u001f\u007f]/.test(path) ||
    path.split("/").some((segment) => segment === ".." || segment === "." || segment.length === 0)
  ) {
    throw new Error(`${label} must not be absolute, traversing, or malformed: ${value}`);
  }
  return path;
}

function assertRoot(root, label) {
  if (typeof root !== "string" || !ROOTS.has(root)) {
    throw new Error(`${label} must be one of: pi, shared, commands, macosLaunchAgents`);
  }
  return root;
}

function backupPath(root, target) {
  if (root === "pi") return target;
  if (root === "shared") return `external-agents-skills-${target.replaceAll("/", "-")}`;
  if (root === "commands") return `local-bin-${target.replaceAll("/", "-")}`;
  return `macos-launch-agents-${target.replaceAll("/", "-")}`;
}

function assertSource(source, label, repoRoot) {
  const absolute = resolve(repoRoot, source);
  const relativeSource = relative(repoRoot, absolute);
  if (relativeSource.startsWith("..")) {
    throw new Error(`${label} resolves outside the repository: ${source}`);
  }
  if (!existsSync(absolute)) throw new Error(`${label} source does not exist: ${source}`);
  const realSource = realpathSync(absolute);
  const realRelative = relative(repoRoot, realSource);
  if (realRelative.startsWith("..")) {
    throw new Error(`${label} source symlink escapes the repository: ${source}`);
  }
}

function normalizeMap(value, label, root, repoRoot, { filesOnly = false } = {}) {
  const map = assertRecord(value ?? {}, label);
  return Object.entries(map).map(([targetValue, sourceValue]) => {
    const target = assertRelativePath(targetValue, `${label} target`);
    const source = assertRelativePath(sourceValue, `${label} source`);
    assertSource(source, `${label} source`, repoRoot);
    if (filesOnly && !statSync(resolve(repoRoot, source)).isFile()) {
      throw new Error(`${label} source must be a file: ${source}`);
    }
    return { root, source, target, backup: backupPath(root, target) };
  });
}

function normalizeCopied(value, repoRoot) {
  if (!Array.isArray(value ?? [])) throw new Error("copied must be an array");
  return value.map((item, index) => {
    const path = assertRelativePath(item, `copied[${index}]`);
    assertSource(path, `copied[${index}]`, repoRoot);
    if (!statSync(resolve(repoRoot, path)).isFile()) {
      throw new Error(`copied[${index}] source must be a file: ${path}`);
    }
    return { root: "pi", source: path, target: path, backup: backupPath("pi", path) };
  });
}

function normalizeRetired(value) {
  const roots = assertRecord(value ?? {}, "retired");
  const entries = [];
  for (const root of ["pi", "shared", "commands"]) {
    const targets = roots[root] ?? [];
    if (!Array.isArray(targets)) throw new Error(`retired.${root} must be an array`);
    for (const [index, item] of targets.entries()) {
      const target = assertRelativePath(item, `retired.${root}[${index}]`);
      entries.push({ root, target, backup: backupPath(root, target) });
    }
  }
  for (const root of Object.keys(roots)) assertRoot(root, `retired.${root}`);
  return entries;
}

function normalizePaths(value, label, { allowTrailingSlash = false } = {}) {
  const items = value ?? [];
  if (!Array.isArray(items)) throw new Error(`${label} must be an array`);
  return items.map((item, index) =>
    assertRelativePath(item, `${label}[${index}]`, { allowTrailingSlash }),
  );
}

function assertUniqueTargets(entries, label) {
  const seen = new Map();
  for (const entry of entries) {
    const key = `${entry.root}:${entry.target}`;
    const previous = seen.get(key);
    if (previous) {
      throw new Error(
        `duplicate managed target ${entry.root}/${entry.target} in ${previous} and ${label}`,
      );
    }
    seen.set(key, label);
  }
}

function assertDisjointTargets(entries) {
  for (let leftIndex = 0; leftIndex < entries.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < entries.length; rightIndex += 1) {
      const left = entries[leftIndex];
      const right = entries[rightIndex];
      if (
        left.root === right.root &&
        (left.target.startsWith(`${right.target}/`) || right.target.startsWith(`${left.target}/`))
      ) {
        throw new Error(`managed targets overlap in ${left.root}: ${left.target} and ${right.target}`);
      }
    }
  }
}

function assertUniqueBackups(entries) {
  const seen = new Map();
  for (const entry of entries) {
    const previous = seen.get(entry.backup);
    if (previous) throw new Error(`backup path collision: ${entry.backup} in ${previous} and manifest`);
    seen.set(entry.backup, entry.target);
  }
}

export function normalizeManifest(raw, { repoRoot = REPO_ROOT } = {}) {
  assertRecord(raw, "manifest");
  const allowedKeys = new Set([
    "version",
    "rendered",
    "copied",
    "linked",
    "commands",
    "sharedSkills",
    "macosLaunchAgents",
    "retired",
    "externalLinks",
    "localOverrides",
    "runtimeExclusions",
  ]);
  const unknownKeys = Object.keys(raw).filter((key) => !allowedKeys.has(key));
  if (unknownKeys.length) throw new Error(`unknown manifest keys: ${unknownKeys.join(", ")}`);
  if (raw.version !== MANIFEST_VERSION) {
    throw new Error(`manifest version must be ${MANIFEST_VERSION}`);
  }

  const rendered = normalizeMap(raw.rendered, "rendered", "pi", repoRoot, { filesOnly: true });
  if (rendered.length !== 1) throw new Error("rendered must contain exactly one settings entry");
  const copied = normalizeCopied(raw.copied, repoRoot);
  const linked = normalizeMap(raw.linked, "linked", "pi", repoRoot);
  const commands = normalizeMap(raw.commands, "commands", "commands", repoRoot, {
    filesOnly: true,
  });
  const sharedSkills = normalizeMap(raw.sharedSkills, "sharedSkills", "shared", repoRoot);
  const macosLaunchAgents = normalizeMap(
    raw.macosLaunchAgents,
    "macosLaunchAgents",
    "macosLaunchAgents",
    repoRoot,
    { filesOnly: true },
  );
  const retired = normalizeRetired(raw.retired);
  const externalLinks = normalizePaths(raw.externalLinks, "externalLinks");
  const localOverrides = normalizePaths(raw.localOverrides, "localOverrides");
  const runtimeExclusions = normalizePaths(raw.runtimeExclusions, "runtimeExclusions", {
    allowTrailingSlash: true,
  });

  assertUniqueTargets(
    [...rendered, ...copied, ...linked, ...commands, ...sharedSkills, ...macosLaunchAgents, ...retired],
    "manifest",
  );
  const managedEntries = [
    ...rendered,
    ...copied,
    ...linked,
    ...commands,
    ...sharedSkills,
    ...macosLaunchAgents,
    ...retired,
  ];
  assertDisjointTargets(managedEntries);
  assertUniqueBackups(managedEntries);
  for (const target of externalLinks) {
    if (managedEntries.some((entry) => entry.root === "pi" && (
      entry.target === target || entry.target.startsWith(`${target}/`) || target.startsWith(`${entry.target}/`)
    ))) {
      throw new Error(`external link conflicts with a managed Pi target: ${target}`);
    }
  }
  if (new Set(runtimeExclusions).size !== runtimeExclusions.length) {
    throw new Error("runtimeExclusions contains duplicate paths");
  }
  if (new Set(localOverrides).size !== localOverrides.length) {
    throw new Error("localOverrides contains duplicate paths");
  }
  if (new Set(externalLinks).size !== externalLinks.length) {
    throw new Error("externalLinks contains duplicate paths");
  }

  return {
    version: MANIFEST_VERSION,
    rendered,
    copied,
    linked,
    commands,
    sharedSkills,
    macosLaunchAgents,
    retired,
    externalLinks,
    localOverrides,
    runtimeExclusions,
  };
}

export function loadManifest(manifestPath = resolve(REPO_ROOT, "config/manifest.json"), options = {}) {
  let raw;
  try {
    raw = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch (error) {
    throw new Error(`could not parse manifest ${manifestPath}`, { cause: error });
  }
  return normalizeManifest(raw, { repoRoot: options.repoRoot ?? REPO_ROOT });
}

export function entriesFor(manifest, category, root) {
  if (category === "shared") return manifest.sharedSkills;
  if (category === "commands") return manifest.commands;
  if (category === "macosLaunchAgents") return manifest.macosLaunchAgents;
  if (category === "retired") return manifest.retired.filter((entry) => entry.root === root);
  if (category === "linked") {
    return manifest.linked.filter((entry) => entry.root === (root ?? "pi"));
  }
  if (category === "rendered") return manifest.rendered;
  if (category === "copied") return manifest.copied;
  if (category === "externalLinks") return manifest.externalLinks.map((target) => ({ target }));
  if (category === "localOverrides") return manifest.localOverrides.map((target) => ({ target }));
  if (category === "runtimeExclusions") return manifest.runtimeExclusions.map((target) => ({ target }));
  throw new Error(`unknown manifest entry category: ${category}`);
}

function printEntries(entries, { includeSource = true } = {}) {
  for (const entry of entries) {
    const fields = includeSource && entry.source
      ? [entry.source, entry.target]
      : [entry.target];
    if (entry.backup) fields.push(entry.backup);
    process.stdout.write(`${fields.join("\t")}\n`);
  }
}

function main(argv) {
  const manifest = loadManifest();
  const [command, category, root] = argv;
  if (command === "validate") {
    process.stdout.write(
      `${JSON.stringify({
        valid: true,
        version: manifest.version,
        copied: manifest.copied.length,
        linked: manifest.linked.length,
        commands: manifest.commands.length,
        sharedSkills: manifest.sharedSkills.length,
        macosLaunchAgents: manifest.macosLaunchAgents.length,
        retired: manifest.retired.length,
      })}\n`,
    );
    return;
  }
  if (command === "list") {
    if (["retired", "externalLinks", "localOverrides", "runtimeExclusions"].includes(category)) {
      printEntries(entriesFor(manifest, category, root), { includeSource: false });
    }
    else printEntries(entriesFor(manifest, category, root));
    return;
  }
  if (command === "check-inventory") {
    const inventory = readFileSync(0, "utf8").split(/\r?\n/).filter(Boolean);
    const excluded = manifest.runtimeExclusions;
    const violations = inventory.filter((path) => excluded.some((item) => {
      if (!item.includes("/")) return path.split("/").includes(item);
      return path === item || path.startsWith(`${item}/`) || path.includes(`/${item}/`);
    }));
    if (violations.length) throw new Error(`repository inventory includes runtime exclusions: ${violations.join(", ")}`);
    return;
  }
  throw new Error("Usage: manifest.mjs validate | check-inventory | list <rendered|copied|linked|commands|shared|macosLaunchAgents|retired|externalLinks|localOverrides|runtimeExclusions> [root]");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`manifest: ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
