"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  approveRecommendation,
  getMission,
  listRecommendations,
  listRuns,
  rejectRecommendation,
} from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Metric, Provenance } from "@/components/Provenance";
import { Badge, Button, Card, Empty, ErrorNote, SectionTitle } from "@/components/ui";
import type { AgentRun, MissionSummary, Recommendation } from "@/lib/types";

const RUNNING = new Set(["created", "active", "planning"]);

export default function MissionPage() {
  const params = useParams<{ brandId: string; missionId: string }>();
  const { brandId, missionId } = params;

  const [summary, setSummary] = useState<MissionSummary | null>(null);
  const [recs, setRecs] = useState<Recommendation[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [note, setNote] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, r, ar] = await Promise.all([
        getMission(missionId),
        listRecommendations(brandId),
        listRuns(missionId),
      ]);
      setSummary(s);
      setRecs(r);
      setRuns(ar);
      return s;
    } catch (err) {
      setError(err as ApiError);
      return null;
    }
  }, [brandId, missionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // While the mission is still running, poll — the run was dispatched in the
  // background and returns 202, so the dashboard fills in as stages complete.
  useEffect(() => {
    if (!summary) return;
    if (!RUNNING.has(summary.mission.status)) return;
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [summary, refresh]);

  async function decide(id: string, approve: boolean) {
    setError(null);
    try {
      if (approve) await approveRecommendation(id, note);
      else await rejectRecommendation(id, note);
      setNote("");
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  if (!summary) {
    return (
      <Shell>
        <ErrorNote error={error} />
        {!error && <Empty>Loading…</Empty>}
      </Shell>
    );
  }

  const m = summary.mission;
  const running = RUNNING.has(m.status);

  return (
    <Shell>
      <div className="mb-4">
        <Link href={`/brands/${brandId}`} className="text-sm text-text-dim hover:text-text">
          ← Brand
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-lg font-semibold">{m.objective}</h1>
          <Badge tone={statusTone(m.status)}>{m.status}</Badge>
          {running && <span className="text-xs text-text-dim">updating…</span>}
        </div>
        <p className="mt-1 text-sm text-text-dim">{m.plan_summary}</p>
      </div>

      <ErrorNote error={error} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <SectionTitle>Baseline</SectionTitle>
          {summary.baseline.value === null ? (
            <p className="text-sm text-text-dim">
              {summary.baseline.note ??
                "No baseline could be measured, so progress against a target cannot be computed. None has been estimated."}
            </p>
          ) : (
            <div className="space-y-1">
              <Metric
                value={summary.baseline.value}
                provenance={summary.baseline.provenance}
                source={summary.baseline.source}
              />
              <div className="text-xs text-text-dim">
                target metric: {summary.target.metric ?? "none"}
              </div>
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle>Progress</SectionTitle>
          <div className="mb-2 h-2 w-full overflow-hidden rounded bg-surface-2">
            <div
              className="h-full bg-accent transition-all"
              style={{ width: `${summary.tasks.percent_complete}%` }}
            />
          </div>
          <div className="text-sm text-text-dim">
            {summary.tasks.completed} of {summary.tasks.total} stage(s) complete
            {summary.tasks.failed > 0 && (
              <span className="ml-1 text-red-300">· {summary.tasks.failed} failed</span>
            )}
          </div>
        </Card>

        <Card>
          <SectionTitle>Measured metrics</SectionTitle>
          {summary.metrics.length === 0 ? (
            <p className="text-sm text-text-dim">No metrics recorded yet.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {summary.metrics.slice(0, 6).map((metric, i) => (
                <li key={i} className="flex items-center justify-between gap-2">
                  <span className="text-text-dim">{metric.metric}</span>
                  <Metric
                    value={metric.value}
                    provenance={metric.provenance}
                    unit={metric.unit}
                  />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Task graph</SectionTitle>
          <ol className="space-y-2">
            {summary.graph.nodes.map((node) => (
              <li key={node.task_id} className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">
                    {node.stage ?? node.type}
                    <span className="ml-2 text-xs text-text-dim">{node.agent_id}</span>
                  </div>
                  <div className="text-xs text-text-dim">{node.objective}</div>
                  {node.error && (
                    <div className="mt-0.5 text-xs text-red-300">{node.error}</div>
                  )}
                </div>
                <Badge tone={taskTone(node.status)}>{node.status}</Badge>
              </li>
            ))}
          </ol>
          {m.strategy && Array.isArray((m.strategy as { excluded?: unknown }).excluded) && (
            <ExcludedStages strategy={m.strategy} />
          )}
        </Card>

        <Card>
          <SectionTitle>Agent runs</SectionTitle>
          {runs.length === 0 ? (
            <p className="text-sm text-text-dim">No runs yet.</p>
          ) : (
            <ul className="space-y-2">
              {runs.map((run) => (
                <li key={run.id} className="border-b border-border pb-2 last:border-0">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">{run.agent_id}</span>
                    <span className="flex items-center gap-2 text-xs text-text-dim">
                      {run.confidence !== null && <span>conf {run.confidence.toFixed(2)}</span>}
                      <Badge tone={taskTone(run.status)}>{run.status}</Badge>
                    </span>
                  </div>
                  {run.summary && (
                    <p className="mt-1 text-xs text-text-dim">{run.summary}</p>
                  )}
                  {run.limitations.length > 0 && (
                    <ul className="mt-1 list-inside list-disc text-xs text-amber-300/80">
                      {run.limitations.slice(0, 3).map((lim, i) => (
                        <li key={i}>{lim}</li>
                      ))}
                    </ul>
                  )}
                  {run.security_flags.length > 0 && (
                    <div className="mt-1">
                      <Badge tone="bad">
                        {run.security_flags.length} security flag(s)
                      </Badge>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-4">
        <SectionTitle>Recommendations</SectionTitle>
        {recs.length === 0 ? (
          <Empty>
            No recommendations yet. They appear once the decision stage has run.
          </Empty>
        ) : (
          <div className="space-y-3">
            {recs.map((rec) => (
              <Card key={rec.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{rec.title}</span>
                      {rec.is_hypothesis ? (
                        <Badge tone="warn">hypothesis</Badge>
                      ) : (
                        <Badge tone="good">{rec.evidence_refs.length} evidence</Badge>
                      )}
                      {rec.approval_required && <Badge tone="warn">approval required</Badge>}
                      <Badge tone="default">{rec.status}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-text-dim">{rec.reason}</p>
                    {rec.expected_outcome && (
                      <p className="mt-1 text-xs text-text-dim">
                        Expected: {rec.expected_outcome}
                      </p>
                    )}
                    {rec.approval_reason && (
                      <p className="mt-1 text-xs text-amber-300/80">{rec.approval_reason}</p>
                    )}
                  </div>
                  <div className="shrink-0 text-right text-xs text-text-dim">
                    <div>priority {rec.priority_score.toFixed(0)}</div>
                    <div>risk {rec.risk}</div>
                  </div>
                </div>
                {rec.status === "proposed" && (
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      className="flex-1 rounded border border-border bg-surface-2 px-2 py-1 text-xs outline-none focus:border-accent"
                      placeholder="Decision note (optional)"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <Button onClick={() => decide(rec.id, true)}>Approve</Button>
                    <Button variant="danger" onClick={() => decide(rec.id, false)}>
                      Reject
                    </Button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}

function ExcludedStages({ strategy }: { strategy: Record<string, unknown> }) {
  const excluded = (strategy.excluded as { stage: string; reason: string }[]) ?? [];
  if (excluded.length === 0) return null;
  return (
    <details className="mt-3 text-xs text-text-dim">
      <summary className="cursor-pointer">
        {excluded.length} stage(s) not run — why
      </summary>
      <ul className="mt-2 space-y-1">
        {excluded.map((s) => (
          <li key={s.stage}>
            <span className="font-medium">{s.stage}</span>: {s.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}

function statusTone(status: string): "default" | "good" | "warn" | "bad" | "info" {
  if (status === "achieved") return "good";
  if (status === "failed") return "bad";
  if (status === "active" || status === "monitoring") return "info";
  return "default";
}

function taskTone(status: string): "default" | "good" | "warn" | "bad" | "info" {
  if (status === "completed") return "good";
  if (status === "failed") return "bad";
  if (status === "blocked") return "warn";
  if (status === "running") return "info";
  return "default";
}
