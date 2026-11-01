"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  addWebsite,
  connectIntegration,
  getBrand,
  listIntegrations,
  listMissions,
  listWebsites,
  planMission,
  runMission,
} from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, SectionTitle } from "@/components/ui";
import type { Brand, Integration, Mission, Website } from "@/lib/types";

const PROVIDERS = [
  { id: "google_search_console", label: "Search Console" },
  { id: "google_analytics_4", label: "Analytics 4" },
];

export default function BrandDetailPage() {
  const params = useParams<{ brandId: string }>();
  const brandId = params.brandId;
  const router = useRouter();

  const [brand, setBrand] = useState<Brand | null>(null);
  const [websites, setWebsites] = useState<Website[]>([]);
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [objective, setObjective] = useState("Increase qualified organic leads");

  const refresh = useCallback(async () => {
    try {
      const [b, w, i, m] = await Promise.all([
        getBrand(brandId),
        listWebsites(brandId),
        listIntegrations(brandId),
        listMissions(brandId),
      ]);
      setBrand(b);
      setWebsites(w);
      setIntegrations(i);
      setMissions(m);
    } catch (err) {
      setError(err as ApiError);
    }
  }, [brandId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onAddWebsite(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await addWebsite(brandId, websiteUrl);
      setWebsiteUrl("");
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  async function onConnect(provider: string) {
    setError(null);
    try {
      await connectIntegration(brandId, provider);
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  async function onPlanAndRun(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const { mission } = await planMission(brandId, {
        objective,
        website_id: websites[0]?.id,
      });
      await runMission(mission.id);
      router.push(`/brands/${brandId}/missions/${mission.id}`);
    } catch (err) {
      setError(err as ApiError);
    }
  }

  const input =
    "rounded border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent";

  if (!brand) {
    return (
      <Shell>
        <ErrorNote error={error} />
        {!error && <Empty>Loading…</Empty>}
      </Shell>
    );
  }

  return (
    <Shell>
      <div className="mb-4">
        <Link href="/brands" className="text-sm text-text-dim hover:text-text">
          ← Brands
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-lg font-semibold">{brand.name}</h1>
          {brand.risk_category !== "general" && (
            <Badge tone="warn">{brand.risk_category} category</Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-text-dim">
          {brand.description || brand.industry || "No description recorded."}
        </p>
      </div>

      <ErrorNote error={error} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle>Website</SectionTitle>
          {websites.length === 0 ? (
            <form onSubmit={onAddWebsite} className="flex items-end gap-2">
              <input
                className={`${input} flex-1`}
                placeholder="https://example.com"
                value={websiteUrl}
                onChange={(e) => setWebsiteUrl(e.target.value)}
                required
              />
              <Button type="submit">Add</Button>
            </form>
          ) : (
            <ul className="space-y-1 text-sm">
              {websites.map((w) => (
                <li key={w.id} className="flex items-center justify-between">
                  <span>{w.base_url}</span>
                  <span className="text-xs text-text-dim">
                    {w.last_crawled_at ? "crawled" : "not yet crawled"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionTitle>Integrations</SectionTitle>
          <div className="space-y-2">
            {PROVIDERS.map((p) => {
              const connected = integrations.find((i) => i.provider === p.id);
              return (
                <div key={p.id} className="flex items-center justify-between text-sm">
                  <span>{p.label}</span>
                  {connected ? (
                    <span className="flex items-center gap-2">
                      {connected.mode === "development_adapter" ? (
                        <Badge tone="warn">synthetic (dev adapter)</Badge>
                      ) : (
                        <Badge tone="good">connected</Badge>
                      )}
                    </span>
                  ) : (
                    <Button variant="ghost" onClick={() => onConnect(p.id)}>
                      Connect
                    </Button>
                  )}
                </div>
              );
            })}
            {integrations.some((i) => i.mode === "development_adapter") && (
              <p className="mt-2 text-xs text-amber-300/80">
                A provider is connected through the development adapter. Every figure it
                produces is synthetic demonstration data and is labelled as such — it does
                not describe this business.
              </p>
            )}
          </div>
        </Card>
      </div>

      <Card className="mt-4">
        <SectionTitle>Start a mission</SectionTitle>
        <form onSubmit={onPlanAndRun} className="flex flex-wrap items-end gap-3">
          <input
            className={`${input} min-w-[20rem] flex-1`}
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            required
          />
          <Button type="submit" disabled={websites.length === 0}>
            Plan &amp; run
          </Button>
          {websites.length === 0 && (
            <span className="text-xs text-text-dim">Add a website first.</span>
          )}
        </form>
      </Card>

      <div className="mt-4">
        <SectionTitle>Missions</SectionTitle>
        {missions.length === 0 ? (
          <Empty>No missions yet.</Empty>
        ) : (
          <div className="space-y-2">
            {missions.map((m) => (
              <Link key={m.id} href={`/brands/${brandId}/missions/${m.id}`}>
                <Card className="transition hover:border-accent">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="font-medium">{m.objective}</div>
                      <div className="mt-0.5 text-xs text-text-dim">
                        {m.mission_type} · target: {m.target_metric ?? "none"}
                      </div>
                    </div>
                    <Badge tone={statusTone(m.status)}>{m.status}</Badge>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}

function statusTone(status: string): "default" | "good" | "warn" | "bad" | "info" {
  if (status === "achieved") return "good";
  if (status === "failed") return "bad";
  if (status === "active" || status === "monitoring") return "info";
  return "default";
}
