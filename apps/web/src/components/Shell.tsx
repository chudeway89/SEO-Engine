"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { logout, me } from "@/lib/api";
import type { Me } from "@/lib/types";

// The authenticated shell. It also guards the page: if there is no valid
// session, it sends the viewer to /login rather than rendering an empty app.
export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [identity, setIdentity] = useState<Me | null>(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((m) => {
        if (!cancelled) setIdentity(m);
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-text-dim">
        Loading…
      </div>
    );
  }
  if (!identity) return null;

  const nav = [
    { href: "/brands", label: "Brands" },
    { href: "/agents", label: "Agents" },
  ];

  return (
    <div className="min-h-screen">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-6">
            <Link href="/brands" className="font-semibold">
              SEO&nbsp;Engine
            </Link>
            <nav className="flex gap-4 text-sm text-text-dim">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={
                    pathname.startsWith(item.href) ? "text-text" : "hover:text-text"
                  }
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-3 text-sm text-text-dim">
            <span>
              {identity.email}
              <span className="ml-2 rounded bg-surface-2 px-1.5 py-0.5 text-xs">
                {identity.role}
              </span>
            </span>
            <span className="text-border">·</span>
            <span>{identity.tenant.name}</span>
            <button
              onClick={() => {
                logout();
                router.replace("/login");
              }}
              className="rounded border border-border px-2 py-1 hover:bg-surface-2"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
