"use client";

import { useEffect, useState } from "react";
import { ApiError, listAgents } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Badge, Card, Empty, ErrorNote } from "@/components/ui";
import type { AgentSummary } from "@/lib/types";

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch((err) => setError(err as ApiError))
      .finally(() => setLoading(false));
  }, []);

  return (
    <Shell>
      <h1 className="mb-1 text-lg font-semibold">Agents</h1>
      <p className="mb-4 text-sm text-text-dim">
        Every agent declares its capabilities, tools, memory scopes, risk and approval
        requirements. It runs only through the Agent Runtime and reaches data only through
        tenant-scoped services.
      </p>

      <ErrorNote error={error} />

      {loading ? (
        <Empty>Loading…</Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {agents.map((agent) => (
            <Card key={agent.id}>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="font-medium">{agent.name}</div>
                  <div className="text-xs text-text-dim">{agent.id}</div>
                </div>
                <Badge tone={agent.risk_level === "low" ? "good" : "warn"}>
                  {agent.risk_level} risk
                </Badge>
              </div>
              <p className="mt-2 text-sm text-text-dim">{agent.description}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {agent.capabilities.map((cap) => (
                  <Badge key={cap} tone="info">
                    {cap}
                  </Badge>
                ))}
              </div>
              {agent.approval_required_for.length > 0 && (
                <div className="mt-2 text-xs text-amber-300/80">
                  Requires approval for: {agent.approval_required_for.join(", ")}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </Shell>
  );
}
