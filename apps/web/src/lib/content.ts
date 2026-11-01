// Content helpers shared by the content pages.

import type { ContentVersion } from "./types";

/** The opening of the notice the platform puts on an outline it assembled
 * from a brief when no model wrote the piece (see
 * packages/engines/seo_engine/engines/content/generation.py). */
const OUTLINE_MARKER = "This is a structured outline, not finished prose.";

export function isOutline(version: ContentVersion | null | undefined): boolean {
  return !!version && version.body_markdown.includes(OUTLINE_MARKER);
}

/** The outline without its notice line, as a starting point for the writer.
 * The API refuses a version that still carries the notice. */
export function stripOutlineNotice(body: string): string {
  return body
    .split("\n")
    .filter((line) => !line.replace(/^>\s*/, "").startsWith(OUTLINE_MARKER))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n");
}

export function authorLabel(version: ContentVersion): string {
  if (version.synthesis_mode === "human") return "written by a person";
  if (isOutline(version)) return `outline from the brief (${version.created_by_agent ?? "agent"})`;
  if (version.synthesis_mode === "llm") return `drafted by a model (${version.created_by_agent ?? "agent"})`;
  return version.created_by_agent ? `by ${version.created_by_agent}` : "by a person";
}

export function contentStatusTone(
  status: string,
): "default" | "good" | "warn" | "bad" | "info" {
  if (status === "published") return "good";
  if (status === "approved") return "info";
  if (status === "in_review") return "warn";
  return "default";
}

export const EVALUATION_LABELS: Record<string, string> = {
  quality_evaluation: "Quality evaluation (CNT-007)",
  quality_gate: "Quality gate (CNT-009)",
  policy_review: "Policy review (POL-001)",
};
