// The typed API client.
//
// One place that knows the envelope shape, the token, and how an error comes
// back. Every call returns `data` unwrapped, or throws an ApiError carrying the
// code, message and request_id — so a caller handles a real failure, never a
// malformed success.

import type {
  ActionItem,
  AgentRun,
  AgentSummary,
  Brand,
  Envelope,
  Integration,
  Me,
  Mission,
  MissionPlan,
  MissionSummary,
  PageMeta,
  Recommendation,
  Tokens,
  Website,
} from "./types";

const BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

const TOKEN_KEY = "seo_engine_token";

export class ApiError extends Error {
  code: string;
  status: number;
  requestId: string;
  details: Record<string, unknown>;

  constructor(
    status: number,
    body: { code: string; message: string; details?: Record<string, unknown> },
    requestId: string,
  ) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.requestId = requestId;
    this.details = body.details ?? {};
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode); the app still works, login resets */
  }
}

export interface Result<T> {
  data: T;
  meta: PageMeta;
  requestId: string;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  opts: { auth?: boolean } = { auth: true },
): Promise<Result<T>> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (opts.auth !== false) {
    const token = getToken();
    if (token) headers.authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch (cause) {
    throw new ApiError(
      0,
      { code: "NETWORK_ERROR", message: "Could not reach the API." },
      "",
    );
  }

  let json: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      /* non-JSON body: handled below */
    }
  }

  if (!response.ok) {
    const envelope = json as { error?: { code: string; message: string; details?: Record<string, unknown> }; request_id?: string } | null;
    const err = envelope?.error ?? {
      code: "HTTP_ERROR",
      message: `Request failed (${response.status}).`,
    };
    throw new ApiError(response.status, err, envelope?.request_id ?? "");
  }

  const envelope = json as Envelope<T>;
  return {
    data: envelope.data,
    meta: (envelope.meta ?? {}) as unknown as PageMeta,
    requestId: envelope.request_id,
  };
}

// --- auth -------------------------------------------------------------------
export async function register(input: {
  email: string;
  password: string;
  name: string;
  organisation_name: string;
}): Promise<{ user: { id: string; email: string }; tokens: Tokens }> {
  const { data } = await request<{ user: { id: string; email: string }; tokens: Tokens }>(
    "POST",
    "/auth/register",
    input,
    { auth: false },
  );
  setToken(data.tokens.access_token);
  return data;
}

export async function login(input: {
  email: string;
  password: string;
}): Promise<Tokens> {
  const { data } = await request<{ tokens: Tokens }>("POST", "/auth/login", input, {
    auth: false,
  });
  setToken(data.tokens.access_token);
  return data.tokens;
}

export function logout(): void {
  setToken(null);
}

export async function me(): Promise<Me> {
  return (await request<Me>("GET", "/auth/me")).data;
}

// --- brands -----------------------------------------------------------------
export async function listBrands(): Promise<Result<Brand[]>> {
  return request<Brand[]>("GET", "/brands");
}

export async function getBrand(brandId: string): Promise<Brand> {
  return (await request<Brand>("GET", `/brands/${brandId}`)).data;
}

export async function createBrand(input: {
  name: string;
  industry?: string;
  risk_category?: string;
}): Promise<Brand> {
  return (await request<Brand>("POST", "/brands", input)).data;
}

export async function listWebsites(brandId: string): Promise<Website[]> {
  return (await request<Website[]>("GET", `/brands/${brandId}/websites`)).data;
}

export async function addWebsite(brandId: string, url: string): Promise<Website> {
  return (await request<Website>("POST", `/brands/${brandId}/websites`, { url })).data;
}

export async function listIntegrations(brandId: string): Promise<Integration[]> {
  return (await request<Integration[]>("GET", `/brands/${brandId}/integrations`)).data;
}

export async function connectIntegration(
  brandId: string,
  provider: string,
): Promise<Result<Integration>> {
  return request<Integration>("POST", `/brands/${brandId}/integrations`, { provider });
}

// --- missions ---------------------------------------------------------------
export async function listMissions(brandId: string): Promise<Mission[]> {
  return (await request<Mission[]>("GET", `/brands/${brandId}/missions`)).data;
}

export async function planMission(
  brandId: string,
  input: { objective: string; website_id?: string },
): Promise<{ mission: Mission; plan: MissionPlan }> {
  return (
    await request<{ mission: Mission; plan: MissionPlan }>(
      "POST",
      `/brands/${brandId}/missions`,
      input,
    )
  ).data;
}

export async function runMission(missionId: string): Promise<void> {
  await request("POST", `/missions/${missionId}/run`);
}

export async function getMission(missionId: string): Promise<MissionSummary> {
  return (await request<MissionSummary>("GET", `/missions/${missionId}`)).data;
}

// --- decisions --------------------------------------------------------------
export async function listRecommendations(
  brandId: string,
  status?: string,
): Promise<Recommendation[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return (await request<Recommendation[]>("GET", `/brands/${brandId}/recommendations${q}`))
    .data;
}

export async function approveRecommendation(
  id: string,
  note: string,
): Promise<Recommendation> {
  return (
    await request<Recommendation>("POST", `/recommendations/${id}/approve`, { note })
  ).data;
}

export async function rejectRecommendation(
  id: string,
  note: string,
): Promise<Recommendation> {
  return (
    await request<Recommendation>("POST", `/recommendations/${id}/reject`, { note })
  ).data;
}

export async function listActions(brandId: string): Promise<ActionItem[]> {
  return (await request<ActionItem[]>("GET", `/brands/${brandId}/actions`)).data;
}

export async function approveAction(id: string, note: string): Promise<ActionItem> {
  return (await request<ActionItem>("POST", `/actions/${id}/approve`, { note })).data;
}

export async function rejectAction(id: string, note: string): Promise<ActionItem> {
  return (await request<ActionItem>("POST", `/actions/${id}/reject`, { note })).data;
}

// --- agents -----------------------------------------------------------------
export async function listAgents(): Promise<AgentSummary[]> {
  return (await request<AgentSummary[]>("GET", "/agents")).data;
}

export async function listRuns(missionId: string): Promise<AgentRun[]> {
  return (await request<AgentRun[]>("GET", `/agents/runs?mission_id=${missionId}`)).data;
}
