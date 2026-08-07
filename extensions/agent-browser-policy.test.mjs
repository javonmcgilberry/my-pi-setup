import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, it } from "node:test";

import agentBrowserPolicyExtension, {
  evaluateAgentBrowserPolicy,
  inspectUpstreamChatRequests,
  loadAgentBrowserPolicy,
  parseAgentBrowserPolicy,
} from "./agent-browser-policy.ts";

const policy = {
  version: 1,
  upstreamChat: { enabled: false, allowedModels: [] },
  cookieTransfer: {
    enabled: false,
    allowedDomains: ["webflow.com", "wfdev.io"],
  },
};
const temporaryDirectories = [];

afterEach(async () => {
  await Promise.all(
    temporaryDirectories
      .splice(0)
      .map((directory) => rm(directory, { recursive: true, force: true })),
  );
});

function decision(overrides = {}) {
  return evaluateAgentBrowserPolicy({
    toolName: "agent_browser",
    input: { args: ["snapshot", "-i"] },
    policy,
    env: {},
    ...overrides,
  });
}

describe("agent-browser policy", () => {
  it("allows ordinary browser work from any active model and reasoning level", () => {
    assert.equal(decision(), undefined);
    assert.equal(
      decision({
        modelId: "openai-codex/gpt-5.6-sol",
        thinkingLevel: "high",
      }),
      undefined,
    );
    assert.equal(decision({ toolName: "agent_browser_web_search" }), undefined);
  });

  it("blocks nested chat directly and inside batch without mistaking arguments for commands", () => {
    assert.equal(
      inspectUpstreamChatRequests({ args: ["click", "chat"] }).length,
      0,
    );
    assert.deepEqual(
      inspectUpstreamChatRequests({
        args: ["--model", "gateway/luna", "batch"],
        stdin: JSON.stringify([
          ["snapshot", "-i"],
          ["chat", "summarize"],
        ]),
      }),
      [{ model: "gateway/luna" }],
    );
    assert.match(
      decision({ input: { args: ["chat", "summarize"] } }).reason,
      /disabled/,
    );
  });

  it("requires an explicit allowlisted AI Gateway model when nested chat is enabled", () => {
    const enabled = {
      ...policy,
      upstreamChat: { enabled: true, allowedModels: ["gateway/luna"] },
    };
    assert.equal(
      decision({
        policy: enabled,
        input: { args: ["--model", "gateway/luna", "chat", "summarize"] },
      }),
      undefined,
    );
    assert.match(
      decision({ policy: enabled, input: { args: ["chat", "summarize"] } })
        .reason,
      /received none/,
    );
  });

  it("loads strict policy and rejects wildcard cookie domains", async () => {
    const directory = await mkdtemp(
      path.join(os.tmpdir(), "agent-browser-policy-"),
    );
    temporaryDirectories.push(directory);
    const file = path.join(directory, "policy.json");
    await writeFile(file, JSON.stringify(policy));
    assert.deepEqual(loadAgentBrowserPolicy(file), policy);
    assert.deepEqual(
      parseAgentBrowserPolicy({
        ...policy,
        models: {
          allowed: ["openai-codex/gpt-5.6-luna"],
          requiredThinkingLevel: "max",
        },
      }),
      policy,
    );
    await writeFile(
      file,
      JSON.stringify({
        ...policy,
        cookieTransfer: { enabled: true, allowedDomains: ["*.webflow.com"] },
      }),
    );
    assert.throws(() => loadAgentBrowserPolicy(file), /wildcards or URLs/);
    assert.throws(
      () => parseAgentBrowserPolicy({ ...policy, surprise: {} }),
      /unknown keys/,
    );
  });

  it("registers safeguards without blocking ordinary browser calls", async () => {
    const handlers = new Map();
    const commands = new Map();
    agentBrowserPolicyExtension({
      on: (name, handler) => handlers.set(name, handler),
      registerCommand: (name, command) => commands.set(name, command),
    });
    const allowed = await handlers.get("tool_call")(
      {
        toolName: "agent_browser",
        input: { args: ["open", "https://example.com"] },
      },
      {
        model: { provider: "openai-codex", id: "gpt-5.6-sol" },
        thinkingLevel: "max",
      },
    );
    assert.equal(allowed, undefined);
    assert.equal(commands.has("agent-browser-policy"), true);
  });
});
