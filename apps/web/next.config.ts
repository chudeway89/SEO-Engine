import type { NextConfig } from "next";

const config: NextConfig = {
  reactStrictMode: true,
  // Type safety is enforced by `tsc --noEmit` (pnpm typecheck) and the build's
  // own type check; ESLint is not installed in this minimal setup, so don't
  // block the build on it.
  eslint: { ignoreDuringBuilds: true },
  // The API base URL is read in the browser, so it must be a public env var.
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1",
  },
};

export default config;
