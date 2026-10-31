"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, login, register } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [org, setOrg] = useState("");
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await login({ email, password });
      } else {
        await register({ email, password, name, organisation_name: org });
      }
      router.replace("/brands");
    } catch (err) {
      setError(err as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const input =
    "w-full rounded border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent";

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <div className="text-xl font-semibold">SEO&nbsp;Engine</div>
          <p className="mt-1 text-sm text-text-dim">
            An agentic SEO and growth operating system.
          </p>
        </div>
        <Card>
          <form onSubmit={submit} className="space-y-3">
            {mode === "register" && (
              <>
                <input
                  className={input}
                  placeholder="Your name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
                <input
                  className={input}
                  placeholder="Organisation name"
                  value={org}
                  onChange={(e) => setOrg(e.target.value)}
                  required
                />
              </>
            )}
            <input
              className={input}
              type="email"
              placeholder="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <input
              className={input}
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={mode === "register" ? 10 : undefined}
            />
            <ErrorNote error={error} />
            <Button type="submit" disabled={busy}>
              {busy ? "…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>
          <div className="mt-4 text-center text-sm text-text-dim">
            {mode === "login" ? (
              <button onClick={() => setMode("register")} className="hover:text-text">
                Need an account? Register
              </button>
            ) : (
              <button onClick={() => setMode("login")} className="hover:text-text">
                Have an account? Sign in
              </button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
