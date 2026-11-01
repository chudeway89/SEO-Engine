"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, getBrand, listContent } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Badge, Card, Empty, ErrorNote, SectionTitle } from "@/components/ui";
import type { Brand, ContentAsset } from "@/lib/types";
import { contentStatusTone } from "@/lib/content";

const FILTERS = ["all", "draft", "in_review", "approved", "published"] as const;

export default function ContentListPage() {
  const { brandId } = useParams<{ brandId: string }>();
  const [brand, setBrand] = useState<Brand | null>(null);
  const [assets, setAssets] = useState<ContentAsset[] | null>(null);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [error, setError] = useState<ApiError | Error | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [b, a] = await Promise.all([
        getBrand(brandId),
        listContent(brandId, filter === "all" ? undefined : filter),
      ]);
      setBrand(b);
      setAssets(a);
    } catch (err) {
      setError(err as ApiError);
    }
  }, [brandId, filter]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <Shell>
      <div className="mb-4">
        <Link href={`/brands/${brandId}`} className="text-sm text-text-dim hover:text-text">
          ← {brand?.name ?? "Brand"}
        </Link>
        <h1 className="mt-1 text-lg font-semibold">Content</h1>
        <p className="mt-1 text-sm text-text-dim">
          Agents draft, evaluate and gate content. A person writes what a model could not,
          approves what passed review, and approves publication where policy requires it.
        </p>
      </div>

      <ErrorNote error={error} />

      <div className="mb-3 flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded border px-2 py-1 text-xs ${
              filter === f
                ? "border-accent text-text"
                : "border-border text-text-dim hover:text-text"
            }`}
          >
            {f.replace("_", " ")}
          </button>
        ))}
      </div>

      <SectionTitle>Assets</SectionTitle>
      {assets === null ? (
        !error && <Empty>Loading…</Empty>
      ) : assets.length === 0 ? (
        <Empty>
          No content{filter === "all" ? "" : ` in ${filter.replace("_", " ")}`}. A content
          mission writes the first drafts.
        </Empty>
      ) : (
        <div className="space-y-2">
          {assets.map((a) => (
            <Link key={a.id} href={`/brands/${brandId}/content/${a.id}`}>
              <Card className="transition hover:border-accent">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium">{a.title}</div>
                    <div className="mt-0.5 text-xs text-text-dim">
                      {a.asset_type} · version {a.current_version}
                      {a.primary_keyword ? ` · ${a.primary_keyword}` : ""}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {a.is_synthetic && <Badge tone="warn">synthetic</Badge>}
                    <Badge tone={contentStatusTone(a.status)}>
                      {a.status.replace("_", " ")}
                    </Badge>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </Shell>
  );
}
