import type { ExtensionAPI, ToolCallEvent } from "@earendil-works/pi-coding-agent";
import { randomBytes } from "node:crypto";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const TOOL_NAME = "webflow_designer";
const OPERATION = "validate_change";
const PHASE = "execute_candidate";
const MAX_DISPLAY_ITEMS = 8;
const MAX_DISPLAY_STRING = 160;
const APPROVAL_ROOT_ENV = "WEBFLOW_VALIDATION_APPROVAL_ROOT";

type RequestCarrier = {
  request: Record<string, unknown>;
  replace: (value: Record<string, unknown>) => void;
};

type GateDecision = { block: true; reason: string } | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function bounded(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > MAX_DISPLAY_STRING) {
    throw new Error("candidate approval details are malformed");
  }
  return value;
}

function boundedNumber(value: unknown): string {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    value > 900
  ) {
    throw new Error("candidate approval details are malformed");
  }
  return String(value);
}

function approvalRoot(): string {
  return (
    process.env[APPROVAL_ROOT_ENV] ??
    join(homedir(), ".config", "webflow-designer-agent-browser", "host-confirmations")
  );
}

function issueHostConfirmation(approvalDigest: string): string {
  const token = randomBytes(32).toString("hex");
  const root = approvalRoot();
  mkdirSync(root, { recursive: true, mode: 0o700 });
  const path = join(root, `${token}.json`);
  writeFileSync(
    path,
    JSON.stringify({ version: 1, approvalDigest, expiresAt: Math.floor(Date.now() / 1000) + 60 }),
    { encoding: "utf8", mode: 0o600, flag: "wx" },
  );
  chmodSync(path, 0o600);
  return token;
}

function carrier(input: Record<string, unknown>): RequestCarrier | undefined {
  if (isRecord(input) && typeof input.operation === "string") {
    return {
      request: input,
      replace(value) {
        Object.assign(input, value);
      },
    };
  }
  for (const key of ["input", "request", "json"]) {
    const raw = input[key];
    if (typeof raw !== "string" || raw.length > 32 * 1024) continue;
    try {
      const value = JSON.parse(raw);
      if (!isRecord(value)) continue;
      return {
        request: value,
        replace(next) {
          input[key] = JSON.stringify(next);
        },
      };
    } catch {
      // The owning custom tool will report malformed JSON.
    }
  }
  return undefined;
}

function approvalMessage(request: Record<string, unknown>): string {
  const candidate = request.candidate;
  const approvalDigest = bounded(request.approvalDigest);
  if (!isRecord(candidate)) throw new Error("candidate approval details are malformed");
  const evidenceRefs = candidate.evidenceRefs;
  const actions = candidate.actions;
  const target = candidate.target;
  const oracle = candidate.oracle;
  const cleanup = candidate.cleanup;
  const budget = candidate.budget;
  if (
    !Array.isArray(evidenceRefs) ||
    !Array.isArray(actions) ||
    !isRecord(target) ||
    !isRecord(oracle) ||
    !Array.isArray(cleanup) ||
    !isRecord(budget) ||
    evidenceRefs.length === 0 ||
    actions.length === 0 ||
    evidenceRefs.length > MAX_DISPLAY_ITEMS ||
    actions.length > MAX_DISPLAY_ITEMS ||
    cleanup.length > MAX_DISPLAY_ITEMS
  ) {
    throw new Error("candidate approval details are malformed");
  }
  const actionSummary = actions.map((action) => {
    if (!isRecord(action)) throw new Error("candidate approval details are malformed");
    const id = bounded(action.id);
    const op = bounded(action.op);
    const detail = action.operationId ?? action.fact ?? action.selectorKey ?? "";
    return `- ${id}: ${op}${detail ? ` (${bounded(detail)})` : ""}`;
  });
  return [
    "This authorizes one isolated candidate validation run only.",
    `Approval digest: ${approvalDigest.slice(0, 16)}…`,
    `Risk: ${bounded(candidate.riskClass)}`,
    `Target: ${bounded(target.fixture)} / ${bounded(target.document)}`,
    `Evidence: ${evidenceRefs.map(bounded).join(", ")}`,
    "Actions:",
    ...actionSummary,
    `Semantic oracle: ${bounded(oracle.kind)} (${bounded(oracle.fact)})`,
    `Cleanup: ${cleanup.map(bounded).join(", ")}`,
    `Budget: ${boundedNumber(budget.timeoutSeconds)}s, ${boundedNumber(budget.maxRetries)} retries`,
  ].join("\n");
}

export function inspectWebflowValidationExecution(input: unknown): {
  carrier?: RequestCarrier;
  message?: string;
  error?: string;
} {
  if (!isRecord(input)) return {};
  const selected = carrier(input);
  if (
    !selected ||
    selected.request.operation !== OPERATION ||
    selected.request.phase !== PHASE
  ) {
    return {};
  }
  if (
    selected.request.userConfirmed === true ||
    typeof selected.request.hostConfirmation === "string"
  ) {
    return { error: "candidate execution requires interactive host confirmation" };
  }
  try {
    return { carrier: selected, message: approvalMessage(selected.request) };
  } catch (error) {
    return {
      error:
        error instanceof Error
          ? error.message
          : "candidate approval details are malformed",
    };
  }
}

export async function gateWebflowValidationExecution(
  event: ToolCallEvent,
  ctx: { hasUI: boolean; ui: { confirm: (title: string, message: string) => Promise<boolean> } },
): Promise<GateDecision> {
  if (event.toolName !== TOOL_NAME) return undefined;
  const inspection = inspectWebflowValidationExecution(event.input);
  if (!inspection.carrier && !inspection.error) return undefined;
  if (inspection.error) return { block: true, reason: inspection.error };
  const selected = inspection.carrier;
  if (!selected) {
    return { block: true, reason: "candidate approval details are malformed" };
  }
  if (!ctx.hasUI) {
    return { block: true, reason: "candidate execution requires an interactive user confirmation" };
  }
  const confirmed = await ctx.ui.confirm(
    "Run proposed Designer validation once?",
    inspection.message as string,
  );
  if (!confirmed) return { block: true, reason: "candidate validation cancelled by user" };
  let hostConfirmation: string;
  try {
    hostConfirmation = issueHostConfirmation(bounded(selected.request.approvalDigest));
  } catch {
    return { block: true, reason: "host confirmation could not be issued" };
  }
  selected.request.hostConfirmation = hostConfirmation;
  selected.replace(selected.request);
  return undefined;
}

export default function webflowValidationApprovalExtension(pi: ExtensionAPI): void {
  pi.on("tool_call", (event, ctx) => gateWebflowValidationExecution(event, ctx));
}
