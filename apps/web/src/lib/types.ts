// Response shapes from the SEO Engine API. These mirror the serialisers in
// apps/api/seo_engine/api/serialize.py. Fields the platform could not measure
// arrive as null (never an estimate), so every metric type is nullable.

export interface Envelope<T> {
  data: T;
  meta: Record<string, unknown>;
  request_id: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface PageMeta {
  limit: number;
  offset: number;
  count: number;
  total: number | null;
  has_more: boolean;
  summary?: Record<string, unknown>;
  note?: string;
  notice?: string;
}

export type Provenance =
  | "observed"
  | "estimated"
  | "inferred"
  | "user_provided"
  | "synthetic_demo"
  | "unknown";

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  name: string;
  status: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  status: string;
}

export interface Me {
  user_id: string;
  email: string;
  role: string;
  permissions: string[];
  tenant: Tenant;
}

export interface Brand {
  id: string;
  name: string;
  slug: string;
  description: string;
  industry: string | null;
  website: string | null;
  country: string | null;
  primary_language: string;
  business_model: string | null;
  risk_category: string;
  created_at: string | null;
}

export interface Website {
  id: string;
  brand_id: string;
  domain: string;
  base_url: string;
  cms: string | null;
  crawl_frequency: string;
  last_crawled_at: string | null;
  created_at: string | null;
}

export interface Integration {
  id: string;
  provider: string;
  status: string;
  mode: string;
  capabilities: string[];
  settings: Record<string, unknown>;
  account_label: string | null;
  connected_at: string | null;
}

export interface MissionPlanStage {
  stage: string;
  agent_id: string;
  objective: string;
  included: boolean;
  reason: string;
  depends_on: string[];
}

export interface MissionPlan {
  mission_type: string;
  target_metric: string | null;
  summary: string;
  stages: MissionPlanStage[];
}

export interface Mission {
  id: string;
  brand_id: string;
  objective: string;
  mission_type: string;
  status: string;
  target_metric: string | null;
  target_value: number | null;
  baseline: number | null;
  baseline_provenance: Provenance;
  baseline_source: string | null;
  automation_policy: string;
  plan_summary: string;
  strategy: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface GraphNode {
  task_id: string;
  agent_id: string;
  type: string;
  objective: string;
  status: string;
  stage: string | null;
  sequence: number;
  required: boolean;
  selection_reason: string;
  attempts: number;
  error: string | null;
}

export interface GraphEdge {
  from: string;
  to: string;
}

export interface MissionGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface MissionProgress {
  stage: string;
  status: string;
  detail: string;
  percent_complete: number;
  at: string | null;
}

export interface MissionMetric {
  metric: string;
  value: number | null;
  unit: string | null;
  provenance: Provenance;
  source: string | null;
  observed_at: string | null;
}

export interface MissionBaseline {
  value: number | null;
  provenance: Provenance;
  source: string | null;
  note: string | null;
}

export interface MissionSummary {
  mission: Mission;
  baseline: MissionBaseline;
  target: { metric: string | null; value: number | null };
  tasks: { total: number; completed: number; failed: number; percent_complete: number };
  graph: MissionGraph;
  progress: MissionProgress[];
  metrics: MissionMetric[];
}

export interface Recommendation {
  id: string;
  recommendation_type: string;
  title: string;
  problem: string;
  opportunity: string;
  reason: string;
  expected_outcome: string;
  status: string;
  priority_score: number;
  business_impact: number;
  seo_impact: number;
  effort: number;
  risk: string;
  confidence: number;
  is_hypothesis: boolean;
  evidence_refs: string[];
  approval_required: boolean;
  approval_reason: string | null;
  proposed_action: Record<string, unknown> | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string | null;
}

export interface ActionItem {
  id: string;
  action_type: string;
  status: string;
  target: Record<string, unknown>;
  risk: string;
  approval_required: boolean;
  approved_by: string | null;
  approved_at: string | null;
  executed_at: string | null;
  integration_mode: string | null;
  provider: string | null;
  result: Record<string, unknown>;
  error_message: string | null;
  policy_decision: Record<string, unknown>;
  recommendation_id: string | null;
  created_at: string | null;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  agent_version: string;
  status: string;
  objective: string;
  summary: string | null;
  confidence: number | null;
  synthesis_mode: string | null;
  limitations: string[];
  security_flags: Record<string, unknown>[];
  mission_id: string | null;
  brand_id: string | null;
  error_code: string | null;
  latency_ms: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface AgentSummary {
  id: string;
  name: string;
  version: string;
  description: string;
  capabilities: string[];
  tools: string[];
  memory_scopes: string[];
  risk_level: string;
  autonomous_actions: string[];
  approval_required_for: string[];
  tags: string[];
}

// --- content -----------------------------------------------------------------
export interface ContentAsset {
  id: string;
  brand_id: string;
  title: string;
  asset_type: string;
  slug: string | null;
  url: string | null;
  status: string;
  risk_category: string;
  current_version: number;
  primary_keyword: string | null;
  external_ref: Record<string, unknown>;
  is_synthetic: boolean;
  published_at: string | null;
  created_at: string | null;
}

export interface ContentSectionBody {
  heading: string;
  body: string;
}

export interface ContentVersion {
  id: string;
  version: number;
  title: string;
  meta_description: string;
  body_markdown: string;
  word_count: number;
  change_summary: string;
  /** "llm", "deterministic" (an outline assembled from the brief) or "human". */
  synthesis_mode: string;
  sections: ContentSectionBody[];
  cta: string | null;
  cited_source_urls: string[];
  created_by_agent: string | null;
  created_by_user: string | null;
  brief_id: string | null;
  created_at: string | null;
}

export interface EvaluationCriterion {
  criterion: string;
  score: number;
  passed: boolean;
  detail: string;
}

export interface ContentEvaluation {
  id: string;
  content_version_id: string | null;
  evaluation_type: string;
  overall_score: number;
  passed: boolean;
  criteria: EvaluationCriterion[];
  blocking_failures: string[];
  warnings: string[];
  requires_human_review: boolean;
  evaluated_by_agent: string | null;
  created_at: string | null;
}

export interface ContentRepair {
  id: string;
  issue: string;
  repair_type: string;
  detail: Record<string, unknown>;
  applied: boolean;
  performed_by_agent: string | null;
}

export interface ContentRepresentation {
  id: string;
  platform: string;
  audience: string | null;
  objective: string | null;
  format: string | null;
  tone: string | null;
  cta: string | null;
  body: string;
  canonical_source_url: string | null;
  status: string;
}

export interface ContentDetail {
  asset: ContentAsset;
  versions: ContentVersion[];
  current_version_evaluations: ContentEvaluation[];
  repairs: ContentRepair[];
  representations: ContentRepresentation[];
}

export interface ContentSource {
  id: string;
  url: string;
  title: string;
  publisher: string | null;
  tier: string;
  reliability: number;
  supports_claim: string | null;
  verified: boolean;
  published_at: string | null;
  retrieved_at: string | null;
}

export interface AgentRunSummary {
  agent_id: string;
  agent_run_id: string;
  status: string;
  summary: string;
  output: Record<string, unknown>;
  limitations: string[];
}

export interface ReviewResult {
  asset: ContentAsset;
  runs: AgentRunSummary[];
}

export interface PublishResult {
  asset: ContentAsset;
  run: AgentRunSummary;
}

export interface VersionInput {
  title: string;
  meta_description: string;
  body_markdown: string;
  sections?: ContentSectionBody[];
  cta?: string | null;
  change_summary: string;
  cited_source_urls?: string[];
}

// --- strategy preview ----------------------------------------------------------
export interface StrategyStage {
  stage: string;
  agent_id: string;
  depends_on?: string[];
  reason: string;
}

export interface StrategyPreview {
  agent_run_id: string;
  summary: string;
  strategy: {
    objective?: string;
    mission_type?: string;
    target_metric?: string | null;
    stages?: StrategyStage[];
    excluded?: StrategyStage[];
    readiness?: {
      has_website?: boolean;
      connected_providers?: string[];
      competitors_recorded?: number;
      goals_recorded?: number;
    };
    summary?: string;
  };
  next_tasks: Record<string, unknown>[];
  recommendations: Record<string, unknown>[];
  limitations: string[];
}
