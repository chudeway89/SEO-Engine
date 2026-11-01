"use client";

// Content review: the one screen where a person writes, reviews, approves and
// publishes a piece. Every button calls the API; the agents that review and
// publish run through the Agent Runtime there, and this page only shows what
// they concluded — never their deliberation.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  approveAction,
  approveContent,
  getContent,
  listSources,
  publishContent,
  returnToDraft,
  reviewContent,
  writeVersion,
} from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, SectionTitle } from "@/components/ui";
import type {
  AgentRunSummary,
  ContentDetail,
  ContentEvaluation,
  ContentSource,
  ContentVersion,
} from "@/lib/types";
import {
  EVALUATION_LABELS,
  authorLabel,
  contentStatusTone,
  isOutline,
  stripOutlineNotice,
} from "@/lib/content";

const input =
  "w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent";

interface AwaitingAction {
  asset_id?: string;
  action_id: string;
  policy_reason?: string | null;
}

interface BlockedItem {
  asset_id?: string;
  title?: string;
  reasons?: string[];
}

export default function ContentDetailPage() {
  const { brandId, assetId } = useParams<{ brandId: string; assetId: string }>();
  const [detail, setDetail] = useState<ContentDetail | null>(null);
  const [sources, setSources] = useState<ContentSource[]>([]);
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [nextStep, setNextStep] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([getContent(assetId), listSources(brandId)]);
      setDetail(d);
      setSources(s);
    } catch (err) {
      setError(err as ApiError);
    }
  }, [assetId, brandId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function act(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(null);
    }
  }

  const onReview = () =>
    act("review", async () => {
      const result = await reviewContent(assetId);
      setRuns(result.data.runs);
      setNextStep(
        result.data.asset.status === "in_review"
          ? "It passed review and is waiting for a person to approve it."
          : "Review blocked it. Address the blocking findings, write a new version and review again.",
      );
    });

  const onApprove = () =>
    act("approve", async () => {
      await approveContent(assetId, note);
      setNote("");
      setRuns([]);
      setNextStep("Approved. Ask the publishing agent to publish it.");
    });

  const onReturn = () =>
    act("return", async () => {
      await returnToDraft(assetId, note || "returned to draft by a reviewer");
      setNote("");
      setNextStep(null);
    });

  const onPublish = () =>
    act("publish", async () => {
      const result = await publishContent(assetId);
      setRuns([result.run]);
      setNextStep(null);
    });

  const onApproveAction = (actionId: string) =>
    act("approve-action", async () => {
      await approveAction(actionId, note || "publication approved");
      const result = await publishContent(assetId);
      setRuns([result.run]);
    });

  if (!detail) {
    return (
      <Shell>
        <ErrorNote error={error} />
        {!error && <Empty>Loading…</Empty>}
      </Shell>
    );
  }

  const { asset, versions } = detail;
  const current = versions[versions.length - 1] ?? null;
  const outline = isOutline(current);

  return (
    <Shell>
      <div className="mb-4">
        <Link
          href={`/brands/${brandId}/content`}
          className="text-sm text-text-dim hover:text-text"
        >
          ← Content
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">{asset.title}</h1>
          <Badge tone={contentStatusTone(asset.status)}>{asset.status.replace("_", " ")}</Badge>
          {asset.risk_category !== "general" && (
            <Badge tone="warn">{asset.risk_category} category</Badge>
          )}
          {asset.is_synthetic && <Badge tone="warn">synthetic</Badge>}
        </div>
        <p className="mt-1 text-xs text-text-dim">
          version {asset.current_version}
          {current ? ` · ${authorLabel(current)}` : ""}
          {asset.url ? ` · ${asset.url}` : ""}
        </p>
      </div>

      <ErrorNote error={error} />

      {outline && (
        <div className="mb-4 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
          The current version is a structured outline, not prose: no model wrote it (none is
          connected, or the connected one could not), so no article text was generated. Write
          the piece below — the outline’s headings are pre-filled — then run the review.
        </div>
      )}

      <Card className="mb-4">
        <SectionTitle>Editorial decision</SectionTitle>
        <div className="flex flex-wrap items-center gap-2">
          {asset.status === "draft" && (
            <Button onClick={onReview} disabled={busy !== null || !current}>
              {busy === "review" ? "Reviewing…" : "Run review"}
            </Button>
          )}
          {asset.status === "in_review" && (
            <Button onClick={onApprove} disabled={busy !== null}>
              {busy === "approve" ? "Approving…" : "Approve"}
            </Button>
          )}
          {asset.status === "approved" && (
            <Button onClick={onPublish} disabled={busy !== null}>
              {busy === "publish" ? "Publishing…" : "Publish"}
            </Button>
          )}
          {["in_review", "approved", "published"].includes(asset.status) && (
            <Button variant="ghost" onClick={onReturn} disabled={busy !== null}>
              Return to draft
            </Button>
          )}
          {["in_review", "approved", "published"].includes(asset.status) && (
            <input
              className={`${input} max-w-sm`}
              placeholder="Note for the record (optional)"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
          {asset.status === "published" && (
            <span className="text-sm text-text-dim">
              Published{asset.published_at ? ` ${new Date(asset.published_at).toLocaleString()}` : ""}.
              To change it, return it to draft and write a new version.
            </span>
          )}
        </div>
        <p className="mt-2 text-xs text-text-dim">
          Review runs the evaluator, the quality gate and the policy guardian against the
          current version. Agents can move a draft to review; only a person approves it.
        </p>
        {nextStep && <p className="mt-2 text-sm">{nextStep}</p>}
      </Card>

      {runs.length > 0 && (
        <Card className="mb-4">
          <SectionTitle>Latest agent runs</SectionTitle>
          <div className="space-y-3">
            {runs.map((run) => (
              <RunPanel
                key={run.agent_run_id}
                run={run}
                busy={busy !== null}
                onApproveAction={onApproveAction}
              />
            ))}
          </div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Review of version {asset.current_version}</SectionTitle>
          {detail.current_version_evaluations.length === 0 ? (
            <Empty>This version has not been reviewed yet.</Empty>
          ) : (
            <div className="space-y-4">
              {detail.current_version_evaluations.map((e) => (
                <EvaluationPanel key={e.id} evaluation={e} />
              ))}
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle>Tracked repairs</SectionTitle>
          {detail.repairs.length === 0 ? (
            <Empty>No repairs recorded.</Empty>
          ) : (
            <ul className="space-y-2 text-sm">
              {detail.repairs.map((r) => (
                <li key={r.id} className="flex items-start justify-between gap-2">
                  <span>
                    {r.issue}
                    <span className="ml-1 text-xs text-text-dim">({r.repair_type})</span>
                  </span>
                  <Badge tone={r.applied ? "good" : "default"}>
                    {r.applied ? "applied" : "open"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
          {detail.representations.length > 0 && (
            <>
              <div className="mt-4">
                <SectionTitle>Derivatives</SectionTitle>
              </div>
              <ul className="space-y-1 text-sm">
                {detail.representations.map((r) => (
                  <li key={r.id} className="flex justify-between">
                    <span>{r.platform}</span>
                    <span className="text-xs text-text-dim">{r.status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      </div>

      {["draft", "in_review", "approved"].includes(asset.status) && current && (
        <VersionEditor
          key={current.id}
          current={current}
          sources={sources}
          busy={busy !== null}
          onSave={(input) =>
            act("save", async () => {
              await writeVersion(assetId, input);
              setRuns([]);
              setNextStep("Saved as a new version. Run the review when it is ready.");
            })
          }
        />
      )}

      <Card className="mt-4">
        <SectionTitle>Version history</SectionTitle>
        <ul className="space-y-1 text-sm">
          {[...versions].reverse().map((v) => (
            <li key={v.id} className="flex flex-wrap justify-between gap-2">
              <span>
                v{v.version} · {v.change_summary}
              </span>
              <span className="text-xs text-text-dim">
                {authorLabel(v)} · {v.word_count} words
              </span>
            </li>
          ))}
        </ul>
      </Card>
    </Shell>
  );
}

function EvaluationPanel({ evaluation }: { evaluation: ContentEvaluation }) {
  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">
          {EVALUATION_LABELS[evaluation.evaluation_type] ?? evaluation.evaluation_type}
        </span>
        <span className="flex items-center gap-2">
          <span className="text-xs text-text-dim">{evaluation.overall_score.toFixed(0)}</span>
          <Badge tone={evaluation.passed ? "good" : "bad"}>
            {evaluation.passed ? "passed" : "blocked"}
          </Badge>
        </span>
      </div>
      {evaluation.blocking_failures.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm text-red-200">
          {evaluation.blocking_failures.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {evaluation.warnings.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs text-amber-200/90">
          {evaluation.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {evaluation.criteria.length > 0 && (
        <table className="mt-2 w-full text-xs">
          <tbody>
            {evaluation.criteria.map((c) => (
              <tr key={c.criterion} className="border-t border-border align-top">
                <td className="py-1 pr-2 font-medium">{c.criterion.replace(/_/g, " ")}</td>
                <td className="py-1 pr-2">{c.score.toFixed(0)}</td>
                <td className={`py-1 ${c.passed ? "text-text-dim" : "text-red-200"}`}>
                  {c.detail}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RunPanel({
  run,
  busy,
  onApproveAction,
}: {
  run: AgentRunSummary;
  busy: boolean;
  onApproveAction: (actionId: string) => void;
}) {
  const awaiting = (run.output.awaiting_action_approval as AwaitingAction[] | undefined) ?? [];
  const blocked = (run.output.blocked as BlockedItem[] | undefined) ?? [];
  return (
    <div className="rounded border border-border p-3">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{run.agent_id}</span>
        <Badge tone={run.status === "completed" ? "info" : "bad"}>{run.status}</Badge>
      </div>
      <p className="mt-1 text-sm">{run.summary}</p>
      {blocked.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm text-red-200">
          {blocked.flatMap((b) => b.reasons ?? []).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {awaiting.map((a) => (
        <div key={a.action_id} className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-amber-200">
            Publication waits for approval{a.policy_reason ? `: ${a.policy_reason}` : "."}
          </span>
          <Button onClick={() => onApproveAction(a.action_id)} disabled={busy}>
            Approve publication
          </Button>
        </div>
      ))}
      {run.limitations.length > 0 && (
        <ul className="mt-2 list-disc pl-5 text-xs text-text-dim">
          {run.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function VersionEditor({
  current,
  sources,
  busy,
  onSave,
}: {
  current: ContentVersion;
  sources: ContentSource[];
  busy: boolean;
  onSave: (input: {
    title: string;
    meta_description: string;
    body_markdown: string;
    change_summary: string;
    cited_source_urls: string[];
  }) => void;
}) {
  const startingBody = useMemo(
    () => (isOutline(current) ? stripOutlineNotice(current.body_markdown) : current.body_markdown),
    [current],
  );
  const [title, setTitle] = useState(current.title);
  const [meta, setMeta] = useState(current.meta_description);
  const [body, setBody] = useState(startingBody);
  const [summary, setSummary] = useState(
    isOutline(current) ? "Wrote the piece over the outline" : "Edited by a person",
  );
  // Start from what the current version already cites, so saving does not
  // silently drop a citation.
  const [cited, setCited] = useState<string[]>(() =>
    current.cited_source_urls.filter((url) => sources.some((s) => s.url === url)),
  );

  function toggle(url: string) {
    setCited((prev) => (prev.includes(url) ? prev.filter((u) => u !== url) : [...prev, url]));
  }

  return (
    <Card className="mt-4">
      <SectionTitle>Write a new version</SectionTitle>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          onSave({
            title,
            meta_description: meta,
            body_markdown: body,
            change_summary: summary,
            cited_source_urls: cited,
          });
        }}
      >
        <label className="block text-xs text-text-dim">
          Title
          <input className={`${input} mt-1`} value={title} onChange={(e) => setTitle(e.target.value)} required />
        </label>
        <label className="block text-xs text-text-dim">
          Meta description
          <input className={`${input} mt-1`} value={meta} onChange={(e) => setMeta(e.target.value)} />
        </label>
        <label className="block text-xs text-text-dim">
          Body (Markdown)
          <textarea
            className={`${input} mt-1 min-h-[22rem] font-mono`}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            required
          />
        </label>
        <div>
          <div className="text-xs text-text-dim">
            Cite from the source register. Only sources the platform fetched are verified;
            regulated content needs at least one.
          </div>
          {sources.length === 0 ? (
            <p className="mt-1 text-xs text-text-dim">
              The register is empty. The source and evidence agent (RES-006) adds sources
              during a content mission.
            </p>
          ) : (
            <ul className="mt-1 space-y-1">
              {sources.map((s) => (
                <li key={s.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={cited.includes(s.url)}
                    onChange={() => toggle(s.url)}
                  />
                  <span className="truncate">{s.title || s.url}</span>
                  <Badge tone={s.verified ? "good" : "default"}>
                    {s.verified ? "verified" : "unverified"}
                  </Badge>
                  <span className="text-xs text-text-dim">{s.tier.replace(/_/g, " ")}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <label className="block text-xs text-text-dim">
          What changed
          <input className={`${input} mt-1`} value={summary} onChange={(e) => setSummary(e.target.value)} required />
        </label>
        <div className="flex items-center gap-3">
          <Button type="submit" disabled={busy}>
            Save as version {current.version + 1}
          </Button>
          <span className="text-xs text-text-dim">
            A new version returns the piece to draft; it must pass review again.
          </span>
        </div>
      </form>
    </Card>
  );
}
