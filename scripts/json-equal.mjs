#!/usr/bin/env node

import { readFileSync } from "node:fs";

function normalize(value) {
  if (Array.isArray(value)) return value.map(normalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, normalize(value[key])]),
    );
  }
  return value;
}

const [leftPath, rightPath] = process.argv.slice(2);
if (!leftPath || !rightPath) {
  console.error("Usage: json-equal.mjs <left.json> <right.json>");
  process.exit(2);
}

const left = normalize(JSON.parse(readFileSync(leftPath, "utf8")));
const right = normalize(JSON.parse(readFileSync(rightPath, "utf8")));
process.exit(JSON.stringify(left) === JSON.stringify(right) ? 0 : 1);
