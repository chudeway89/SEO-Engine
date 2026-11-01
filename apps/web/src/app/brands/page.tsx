"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, createBrand, listBrands } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Badge, Button, Card, Empty, ErrorNote, SectionTitle } from "@/components/ui";
import type { Brand } from "@/lib/types";

export default function BrandsPage() {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [risk, setRisk] = useState("general");

  async function refresh() {
    setLoading(true);
    try {
      setBrands((await listBrands()).data);
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await createBrand({ name, industry: industry || undefined, risk_category: risk });
      setName("");
      setIndustry("");
      setCreating(false);
      await refresh();
    } catch (err) {
      setError(err as ApiError);
    }
  }

  const input =
    "rounded border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent";

  return (
    <Shell>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold">Brands</h1>
        <Button onClick={() => setCreating((v) => !v)} variant="ghost">
          {creating ? "Cancel" : "New brand"}
        </Button>
      </div>

      <ErrorNote error={error} />

      {creating && (
        <Card className="mb-4">
          <SectionTitle>New brand</SectionTitle>
          <form onSubmit={create} className="flex flex-wrap items-end gap-3">
            <input
              className={input}
              placeholder="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <input
              className={input}
              placeholder="Industry (optional)"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
            />
            <select className={input} value={risk} onChange={(e) => setRisk(e.target.value)}>
              {["general", "health", "medical", "financial", "legal", "safety", "regulated"].map(
                (r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ),
              )}
            </select>
            <Button type="submit">Create</Button>
          </form>
        </Card>
      )}

      {loading ? (
        <Empty>Loading…</Empty>
      ) : brands.length === 0 ? (
        <Empty>No brands yet. Create one to begin.</Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {brands.map((brand) => (
            <Link key={brand.id} href={`/brands/${brand.id}`}>
              <Card className="h-full transition hover:border-accent">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-medium">{brand.name}</div>
                  {brand.risk_category !== "general" && (
                    <Badge tone="warn">{brand.risk_category}</Badge>
                  )}
                </div>
                <div className="mt-1 text-sm text-text-dim">
                  {brand.industry ?? "Industry not stated"}
                </div>
                {brand.website && (
                  <div className="mt-2 truncate text-xs text-text-dim">{brand.website}</div>
                )}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </Shell>
  );
}
