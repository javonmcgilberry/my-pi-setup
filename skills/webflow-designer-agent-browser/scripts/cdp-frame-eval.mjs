import { basename } from "node:path";
import { realpathSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const SENSITIVE_PARTS = [
  "authorization",
  "cookie",
  "credential",
  "password",
  "secret",
  "token",
];

function usage() {
  return [
    "Usage: node cdp-frame-eval.mjs",
    "  --browser-ws-url <local-cdp-url>",
    "  --page-url-needle <sanitized-host-or-path>",
    "  --frame-url-needle <sanitized-host-or-path>",
    "  --expression-file <path>",
    "  or --visible-replacement-selector <selector>",
    "  [--observation-ms <50-30000>]",
    "  [--dry-run]",
  ].join("\n");
}

function parseArgs(argv) {
  const options = { dryRun: false };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    const value = argv[index + 1];
    if (!value) throw new Error(`Missing value for ${item}`);
    if (item === "--browser-ws-url") options.browserWsUrl = value;
    else if (item === "--page-url-needle") options.pageUrlNeedle = value;
    else if (item === "--frame-url-needle") options.frameUrlNeedle = value;
    else if (item === "--expression-file") options.expressionFile = value;
    else if (item === "--visible-replacement-selector") {
      options.visibleReplacementSelector = value;
    } else if (item === "--observation-ms") {
      options.observationMs = Number(value);
    }
    else throw new Error(`Unknown option: ${item}`);
    index += 1;
  }
  for (const field of ["browserWsUrl", "pageUrlNeedle", "frameUrlNeedle"]) {
    if (!options[field]) throw new Error(`Missing required option: ${field}`);
  }
  const browserUrl = new URL(options.browserWsUrl);
  if (!["ws:", "wss:"].includes(browserUrl.protocol)) {
    throw new Error("Browser WebSocket URL must use ws or wss");
  }
  if (!["127.0.0.1", "::1", "localhost"].includes(browserUrl.hostname)) {
    throw new Error("Browser WebSocket URL must use a loopback host");
  }
  const operationCount = Number(Boolean(options.expressionFile)) +
    Number(Boolean(options.visibleReplacementSelector));
  if (operationCount !== 1) {
    throw new Error(
      "Provide exactly one of --expression-file or --visible-replacement-selector"
    );
  }
  for (const field of ["pageUrlNeedle", "frameUrlNeedle"]) {
    const value = options[field].toLowerCase();
    if (SENSITIVE_PARTS.some(part => value.includes(part))) {
      throw new Error(`Refusing sensitive targeting value: ${field}`);
    }
  }
  if (options.visibleReplacementSelector) {
    if (options.visibleReplacementSelector.length > 240) {
      throw new Error("Visible replacement selector exceeds 240 characters");
    }
    const selector = options.visibleReplacementSelector.toLowerCase();
    if (SENSITIVE_PARTS.some(part => selector.includes(part))) {
      throw new Error("Refusing sensitive visible replacement selector");
    }
    options.observationMs ??= 5000;
    if (
      !Number.isInteger(options.observationMs) ||
      options.observationMs < 50 ||
      options.observationMs > 30000
    ) {
      throw new Error("Observation duration must be an integer from 50 to 30000");
    }
  } else if (options.observationMs !== undefined) {
    throw new Error("--observation-ms requires --visible-replacement-selector");
  }
  return options;
}

function visibleReplacementExpression(selector, observationMs) {
  return `(() => new Promise((resolve) => {
    const selector = ${JSON.stringify(selector)};
    const observationMs = ${observationMs};
    const samples = [];
    const startedAt = performance.now();
    const sample = () => {
      const elements = Array.from(document.querySelectorAll(selector));
      const rendered = elements.filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return !element.hidden && style.display !== "none" &&
          style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      }).length;
      const next = {
        elapsedMs: Math.round(performance.now() - startedAt),
        rendered,
        total: elements.length,
      };
      const previous = samples[samples.length - 1];
      if (!previous || previous.rendered !== next.rendered ||
          previous.total !== next.total) {
        samples.push(next);
      }
    };
    const observer = new MutationObserver(sample);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class", "hidden", "style"],
      childList: true,
      subtree: true,
    });
    sample();
    setTimeout(() => {
      sample();
      observer.disconnect();
      resolve({ samples });
    }, observationMs);
  }))()`;
}

export function summarizeVisibleReplacement(samples) {
  if (!Array.isArray(samples) || samples.length === 0) {
    throw new Error("Visible replacement probe returned no samples");
  }
  for (const sample of samples) {
    if (
      typeof sample !== "object" ||
      sample === null ||
      !Number.isInteger(sample.elapsedMs) ||
      !Number.isInteger(sample.rendered) ||
      !Number.isInteger(sample.total) ||
      sample.elapsedMs < 0 ||
      sample.rendered < 0 ||
      sample.total < sample.rendered
    ) {
      throw new Error("Visible replacement probe returned invalid samples");
    }
  }
  const baselineRendered = samples[0].rendered;
  return {
    baselineRendered,
    blankGapObserved: samples.some(sample => sample.rendered < baselineRendered),
    finalRendered: samples[samples.length - 1].rendered,
    maximumTotal: Math.max(...samples.map(sample => sample.total)),
    overlapObserved: samples.some(sample => sample.rendered > baselineRendered),
    sampleCount: samples.length,
    transitions: samples,
  };
}

function createClient(browserWsUrl) {
  const socket = new WebSocket(browserWsUrl);
  let nextId = 1;
  const pending = new Map();

  function send(method, params = {}, sessionId) {
    const id = nextId++;
    socket.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
    });
  }

  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    if (message.error) {
      request.reject(new Error(JSON.stringify(message.error)));
    } else {
      request.resolve(message.result);
    }
  });
  socket.addEventListener("close", () => {
    for (const request of pending.values()) {
      request.reject(new Error("Browser debugging connection closed"));
    }
    pending.clear();
  });

  return {
    socket,
    send,
    waitForOpen: () => {
      if (socket.readyState === WebSocket.OPEN) return Promise.resolve();
      if (socket.readyState === WebSocket.CLOSED) {
        return Promise.reject(
          new Error("Browser debugging connection is already closed")
        );
      }
      return new Promise((resolve, reject) => {
        socket.addEventListener("open", resolve, { once: true });
        socket.addEventListener("error", reject, { once: true });
        socket.addEventListener(
          "close",
          () => reject(new Error("Browser debugging connection closed")),
          { once: true }
        );
      });
    },
  };
}

async function evaluate(options, expression) {
  const client = createClient(options.browserWsUrl);
  await client.waitForOpen();

  try {
    const { targetInfos } = await client.send("Target.getTargets");
    const page = targetInfos.find(
      target =>
        target.type === "page" &&
        target.url.includes(options.pageUrlNeedle)
    );
    if (!page) throw new Error("No matching page target");

    const frameTarget = targetInfos.find(
      target =>
        target.type === "iframe" &&
        target.url.includes(options.frameUrlNeedle)
    );
    if (frameTarget) {
      const attached = await client.send("Target.attachToTarget", {
        targetId: frameTarget.targetId,
        flatten: true,
      });
      return await evaluateInContext(
        client,
        attached.sessionId,
        expression,
        undefined
      );
    }

    const attached = await client.send("Target.attachToTarget", {
      targetId: page.targetId,
      flatten: true,
    });
    const { frameTree } = await client.send(
      "Page.getFrameTree",
      {},
      attached.sessionId
    );
    const frames = [];
    function visit(node) {
      frames.push(node.frame);
      for (const child of node.childFrames ?? []) visit(child);
    }
    visit(frameTree);
    const frame = frames.find(candidate =>
      candidate.url.includes(options.frameUrlNeedle)
    );
    if (!frame) throw new Error("No matching frame");
    const { executionContextId } = await client.send(
      "Page.createIsolatedWorld",
      {
        frameId: frame.id,
        worldName: "webflow-designer-agent-browser",
        grantUniveralAccess: false,
      },
      attached.sessionId
    );
    return await evaluateInContext(
      client,
      attached.sessionId,
      expression,
      executionContextId
    );
  } finally {
    client.socket.close();
  }
}

async function evaluateInContext(
  client,
  sessionId,
  expression,
  contextId
) {
  const result = await client.send(
    "Runtime.evaluate",
    {
      expression,
      contextId,
      awaitPromise: true,
      returnByValue: true,
    },
    sessionId
  );
  if (result.exceptionDetails) {
    throw new Error("Scoped expression failed");
  }
  return result.result.value;
}

async function main() {
  try {
    const options = parseArgs(process.argv.slice(2));
    const expression = options.expressionFile
      ? await readFile(options.expressionFile, "utf8")
      : visibleReplacementExpression(
          options.visibleReplacementSelector,
          options.observationMs
        );
    if (Buffer.byteLength(expression, "utf8") > 1_000_000) {
      throw new Error("Expression file exceeds 1 MB");
    }
    if (options.dryRun) {
      process.stdout.write(
        JSON.stringify({
          action: "evaluate scoped expression in existing browser frame",
          expressionFile: options.expressionFile
            ? basename(options.expressionFile)
            : null,
          operation: options.visibleReplacementSelector
            ? "observe-visible-replacement"
            : "evaluate-expression",
          targetMetadataIncluded: false,
        })
      );
      return;
    }
    const evaluated = await evaluate(options, expression);
    const value = options.visibleReplacementSelector
      ? summarizeVisibleReplacement(evaluated.samples)
      : evaluated;
    process.stdout.write(JSON.stringify({ value }));
  } catch (error) {
    process.stderr.write(`${error.message}\n${usage()}\n`);
    process.exitCode = 2;
  }
}

if (
  process.argv[1] &&
  realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))
) {
  await main();
}
