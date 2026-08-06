import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const POLICY_ENV = "PI_AGENT_BROWSER_POLICY_CONFIG";
const POLICY_FILE = "agent-browser-policy.json";
const BROWSER_TOOLS = new Set(["agent_browser", "agent_browser_web_search"]);
const THINKING_LEVELS = new Set([
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
]);
const GLOBAL_OPTIONS_WITH_VALUES = new Set([
  "--allowed-domains",
  "--cdp",
  "--device",
  "--executable-path",
  "--idle-timeout",
  "--model",
  "--namespace",
  "--profile",
  "--provider",
  "--session",
  "--session-name",
  "--state",
  "--user-agent",
  "-p",
]);

export type AgentBrowserPolicy = {
  version: 1;
  models: {
    allowed: string[];
    requiredThinkingLevel: string;
  };
  upstreamChat: {
    enabled: boolean;
    allowedModels: string[];
  };
  cookieTransfer: {
    enabled: boolean;
    allowedDomains: string[];
  };
};

type PolicyDecision = { block: true; reason: string } | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertKnownKeys(
  value: Record<string, unknown>,
  allowed: string[],
  path: string,
): void {
  const unknown = Object.keys(value).filter((key) => !allowed.includes(key));
  if (unknown.length > 0) {
    throw new Error(`${path} contains unknown keys: ${unknown.join(", ")}`);
  }
}

function requireStringArray(value: unknown, path: string): string[] {
  if (
    !Array.isArray(value) ||
    value.some((entry) => typeof entry !== "string" || entry.trim() === "")
  ) {
    throw new Error(`${path} must be an array of non-empty strings`);
  }
  return [...new Set(value.map((entry) => entry.trim()))];
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${path} must be an object`);
  return value;
}

function parseModels(value: unknown): AgentBrowserPolicy["models"] {
  const models = requireRecord(value, "models");
  assertKnownKeys(models, ["allowed", "requiredThinkingLevel"], "models");
  const allowed = requireStringArray(models.allowed, "models.allowed");
  if (allowed.length === 0) {
    throw new Error("models.allowed must contain at least one model");
  }
  const requiredThinkingLevel = models.requiredThinkingLevel;
  if (
    typeof requiredThinkingLevel !== "string" ||
    !THINKING_LEVELS.has(requiredThinkingLevel)
  ) {
    throw new Error("models.requiredThinkingLevel is invalid");
  }
  return { allowed, requiredThinkingLevel };
}

function parseUpstreamChat(value: unknown): AgentBrowserPolicy["upstreamChat"] {
  const upstreamChat = requireRecord(value, "upstreamChat");
  assertKnownKeys(upstreamChat, ["enabled", "allowedModels"], "upstreamChat");
  if (typeof upstreamChat.enabled !== "boolean") {
    throw new Error("upstreamChat.enabled must be a boolean");
  }
  const upstreamModels = requireStringArray(
    upstreamChat.allowedModels,
    "upstreamChat.allowedModels",
  );
  if (upstreamChat.enabled && upstreamModels.length === 0) {
    throw new Error(
      "upstreamChat.allowedModels must not be empty when upstream chat is enabled",
    );
  }
  return { enabled: upstreamChat.enabled, allowedModels: upstreamModels };
}

function parseCookieTransfer(value: unknown): AgentBrowserPolicy["cookieTransfer"] {
  const cookieTransfer = requireRecord(value, "cookieTransfer");
  assertKnownKeys(cookieTransfer, ["enabled", "allowedDomains"], "cookieTransfer");
  if (typeof cookieTransfer.enabled !== "boolean") {
    throw new Error("cookieTransfer.enabled must be a boolean");
  }
  const allowedDomains = requireStringArray(
    cookieTransfer.allowedDomains,
    "cookieTransfer.allowedDomains",
  );
  const normalizedDomains = allowedDomains.map((domain) =>
    domain.toLowerCase().replace(/^\.+/, ""),
  );
  if (
    normalizedDomains.some(
      (domain) =>
        !domain ||
        domain.includes("*") ||
        domain.includes("/") ||
        domain.includes(":") ||
        /[\s\u0000-\u001f]/.test(domain),
    )
  ) {
    throw new Error("cookieTransfer.allowedDomains accepts hostnames, not wildcards or URLs");
  }
  if (cookieTransfer.enabled && normalizedDomains.length === 0) {
    throw new Error("cookieTransfer.allowedDomains must not be empty when enabled");
  }
  return {
    enabled: cookieTransfer.enabled,
    allowedDomains: normalizedDomains,
  };
}

export function parseAgentBrowserPolicy(value: unknown): AgentBrowserPolicy {
  const policy = requireRecord(value, "agent-browser policy");
  if (policy.version !== 1) {
    throw new Error("agent-browser policy must be a version 1 object");
  }
  assertKnownKeys(policy, ["version", "models", "upstreamChat", "cookieTransfer"], "policy");
  return {
    version: 1,
    models: parseModels(policy.models),
    upstreamChat: parseUpstreamChat(policy.upstreamChat),
    cookieTransfer: parseCookieTransfer(policy.cookieTransfer),
  };
}

export function resolveAgentBrowserPolicyPath(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const configured = env[POLICY_ENV]?.trim();
  if (configured) {
    return isAbsolute(configured) ? configured : resolve(configured);
  }
  const agentDir = env.PI_AGENT_DIR?.trim() || join(env.HOME || homedir(), ".pi", "agent");
  const installed = join(agentDir, POLICY_FILE);
  if (existsSync(installed)) return installed;
  return join(dirname(dirname(fileURLToPath(import.meta.url))), POLICY_FILE);
}

export function loadAgentBrowserPolicy(
  path = resolveAgentBrowserPolicyPath(),
): AgentBrowserPolicy {
  let raw: string;
  try {
    raw = readFileSync(path, "utf8");
  } catch {
    throw new Error("agent-browser policy could not be read");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("agent-browser policy could not be read or parsed");
  }
  return parseAgentBrowserPolicy(parsed);
}

function commandToken(args: unknown): string | undefined {
  if (!Array.isArray(args) || args.some((entry) => typeof entry !== "string")) {
    return undefined;
  }
  for (let index = 0; index < args.length; index += 1) {
    const token = args[index] as string;
    if (GLOBAL_OPTIONS_WITH_VALUES.has(token)) {
      index += 1;
      continue;
    }
    if (token.startsWith("--") && token.includes("=")) continue;
    if (token.startsWith("-")) continue;
    return token;
  }
  return undefined;
}

function explicitModel(args: unknown): string | undefined {
  if (!Array.isArray(args)) return undefined;
  for (let index = 0; index < args.length; index += 1) {
    const token = args[index];
    if (token === "--model") {
      const value = args[index + 1];
      return typeof value === "string" && value.trim() ? value.trim() : undefined;
    }
    if (typeof token === "string" && token.startsWith("--model=")) {
      return token.slice("--model=".length).trim() || undefined;
    }
  }
  return undefined;
}

export function inspectUpstreamChatRequests(input: unknown): Array<{
  model?: string;
}> {
  if (!isRecord(input)) return [];
  const requests: Array<{ model?: string }> = [];
  const rootModel = explicitModel(input.args);
  if (commandToken(input.args) === "chat") requests.push({ model: rootModel });
  if (commandToken(input.args) !== "batch" || typeof input.stdin !== "string") {
    return requests;
  }
  try {
    const steps = JSON.parse(input.stdin);
    if (!Array.isArray(steps)) return requests;
    for (const step of steps) {
      if (commandToken(step) === "chat") {
        requests.push({ model: explicitModel(step) ?? rootModel });
      }
    }
  } catch {
    // The owning tool reports malformed batch input. Policy does not reinterpret it.
  }
  return requests;
}

type PolicyOptions = {
  toolName: string;
  input: unknown;
  modelId?: string;
  thinkingLevel?: string;
  policy: AgentBrowserPolicy;
  env?: NodeJS.ProcessEnv;
};

function evaluateActiveModel(options: PolicyOptions): PolicyDecision {
  const { policy } = options;
  if (!options.modelId || !policy.models.allowed.includes(options.modelId)) {
    return {
      block: true,
      reason: `agent_browser policy allows ${policy.models.allowed.join(", ")}; active model is ${options.modelId || "unknown"}.`,
    };
  }
  if (options.thinkingLevel !== policy.models.requiredThinkingLevel) {
    return {
      block: true,
      reason: `agent_browser policy requires thinking level ${policy.models.requiredThinkingLevel}; active level is ${options.thinkingLevel || "unknown"}.`,
    };
  }
  return undefined;
}

function evaluateUpstreamChat(options: PolicyOptions): PolicyDecision {
  const { policy } = options;
  const chatRequests = inspectUpstreamChatRequests(options.input);
  if (chatRequests.length === 0) return undefined;
  if (!policy.upstreamChat.enabled) {
    return {
      block: true,
      reason:
        "Nested agent-browser chat is disabled; use deterministic browser commands from the active Pi model.",
    };
  }
  const environmentModel = (options.env ?? process.env).AI_GATEWAY_MODEL?.trim();
  for (const request of chatRequests) {
    const model = request.model ?? environmentModel;
    if (!model || !policy.upstreamChat.allowedModels.includes(model)) {
      return {
        block: true,
        reason: `Nested agent-browser chat requires an explicitly allowed AI Gateway model; received ${model || "none"}.`,
      };
    }
  }
  return undefined;
}

export function evaluateAgentBrowserPolicy(options: PolicyOptions): PolicyDecision {
  if (!BROWSER_TOOLS.has(options.toolName)) return undefined;
  const modelDecision = evaluateActiveModel(options);
  if (modelDecision) return modelDecision;
  if (options.toolName !== "agent_browser") return undefined;
  return evaluateUpstreamChat(options);
}

function activeModelId(ctx: { model?: { provider?: unknown; id?: unknown } } | undefined): string | undefined {
  const provider = ctx?.model?.provider;
  const id = ctx?.model?.id;
  return typeof provider === "string" && typeof id === "string"
    ? `${provider}/${id}`
    : undefined;
}

export default function agentBrowserPolicyExtension(pi: ExtensionAPI): void {
  pi.on("tool_call", (event, ctx) => {
    if (!BROWSER_TOOLS.has(event.toolName)) return undefined;
    try {
      return evaluateAgentBrowserPolicy({
        toolName: event.toolName,
        input: event.input,
        modelId: activeModelId(ctx),
        thinkingLevel: ctx.thinkingLevel,
        policy: loadAgentBrowserPolicy(),
      });
    } catch (error) {
      return {
        block: true,
        reason: `agent_browser policy could not be loaded: ${error instanceof Error ? error.message : "unknown error"}`,
      };
    }
  });

  pi.registerCommand("agent-browser-policy", {
    description: "Show the effective model, nested-chat, and cookie-transfer policy",
    handler: (_args, ctx) => {
      try {
        const policy = loadAgentBrowserPolicy();
        ctx.ui.notify(
          [
            `Models: ${policy.models.allowed.join(", ")} (${policy.models.requiredThinkingLevel})`,
            `Nested chat: ${policy.upstreamChat.enabled ? "enabled" : "disabled"}`,
            `Cookie transfer: ${policy.cookieTransfer.enabled ? "enabled" : "disabled"}`,
            `Cookie domains: ${policy.cookieTransfer.allowedDomains.join(", ") || "none"}`,
          ].join("\n"),
          "info",
        );
      } catch (error) {
        ctx.ui.notify(
          `agent_browser policy error: ${error instanceof Error ? error.message : "unknown error"}`,
          "error",
        );
      }
      return Promise.resolve();
    },
  });
}
