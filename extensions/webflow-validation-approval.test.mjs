import assert from "node:assert/strict";
import { after, describe, it } from "node:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import webflowValidationApprovalExtension, {
  gateWebflowValidationExecution,
  inspectWebflowValidationExecution,
} from "./webflow-validation-approval.ts";

const approvalRoot = mkdtempSync(join(tmpdir(), "webflow-approval-"));
process.env.WEBFLOW_VALIDATION_APPROVAL_ROOT = approvalRoot;
after(() => rmSync(approvalRoot, { recursive: true, force: true }));

function request(overrides = {}) {
  return {
    version: 1,
    operation: "validate_change",
    phase: "execute_candidate",
    approvalDigest: "a".repeat(64),
    candidate: {
      riskClass: "reversible-ui",
      evidenceRefs: ["policy:runner:designer-pages-panel-focused"],
      target: { fixture: "isolated-designer-test", document: "main" },
      actions: [
        { id: "open-panel", op: "invoke_operation", operationId: "designer.panel.pages.open" },
        { id: "assert-panel", op: "assert", fact: "panel-visible" },
      ],
      oracle: { kind: "semantic-fact", fact: "panel-visible" },
      cleanup: ["adapter-teardown"],
      budget: { timeoutSeconds: 900, maxRetries: 1 },
    },
    ...overrides,
  };
}

describe("Webflow validation approval", () => {
  it("ignores unrelated custom-tool operations", () => {
    assert.deepEqual(inspectWebflowValidationExecution({ input: JSON.stringify({ operation: "status" }) }), {});
  });

  it("blocks an untrusted pre-confirmed candidate", async () => {
    const result = await gateWebflowValidationExecution(
      { toolName: "webflow_designer", input: { input: JSON.stringify(request({ userConfirmed: true })) } },
      { hasUI: true, ui: { confirm: async () => true } },
    );
    assert.match(result.reason, /interactive host confirmation/);
  });

  it("blocks candidate execution without an interactive host", async () => {
    const result = await gateWebflowValidationExecution(
      { toolName: "webflow_designer", input: { input: JSON.stringify(request()) } },
      { hasUI: false, ui: { confirm: async () => true } },
    );
    assert.match(result.reason, /interactive user confirmation/);
  });

  it("shows exact bounded approval details and injects confirmation only after consent", async () => {
    const input = { input: JSON.stringify(request()) };
    let prompt = "";
    const result = await gateWebflowValidationExecution(
      { toolName: "webflow_designer", input },
      {
        hasUI: true,
        ui: {
          confirm: async (_title, message) => {
            prompt = message;
            return true;
          },
        },
      },
    );
    assert.equal(result, undefined);
    assert.match(prompt, /one isolated candidate validation run only/);
    assert.match(prompt, /designer.panel.pages.open/);
    assert.match(JSON.parse(input.input).hostConfirmation, /^[0-9a-f]{64}$/);
  });

  it("does not inject confirmation when the user declines", async () => {
    const input = { input: JSON.stringify(request()) };
    const result = await gateWebflowValidationExecution(
      { toolName: "webflow_designer", input },
      { hasUI: true, ui: { confirm: async () => false } },
    );
    assert.match(result.reason, /cancelled by user/);
    assert.equal(JSON.parse(input.input).hostConfirmation, undefined);
  });

  it("registers a single tool-call gate", () => {
    const handlers = new Map();
    webflowValidationApprovalExtension({ on: (name, handler) => handlers.set(name, handler) });
    assert.equal(handlers.has("tool_call"), true);
  });
});
