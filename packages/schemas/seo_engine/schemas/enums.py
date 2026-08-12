"""Canonical enumerations shared by the database, the agents and the API."""

from __future__ import annotations

from enum import StrEnum


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INVITED = "invited"
    DISABLED = "disabled"


class Role(StrEnum):
    """Tenant-scoped roles, ordered from most to least privileged."""

    OWNER = "owner"
    ADMIN = "admin"
    STRATEGIST = "strategist"
    EDITOR = "editor"
    ANALYST = "analyst"
    VIEWER = "viewer"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionLevel(StrEnum):
    """Capability permission levels from the Architecture Pack section 17."""

    DENY = "deny"
    READ = "read"
    PROPOSE = "propose"
    EXECUTE = "execute"
    AUTONOMOUS = "autonomous"


class TaskStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"
    QUEUED = "queued"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    REQUIRES_APPROVAL = "requires_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.EXPIRED,
    }
)


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class MissionStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    ACTIVE = "active"
    MONITORING = "monitoring"
    ADAPTING = "adapting"
    ACHIEVED = "achieved"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AutomationPolicy(StrEnum):
    """How much the system may do without asking."""

    MANUAL = "manual"
    ASSISTED = "assisted"
    APPROVAL_REQUIRED = "approval_required"
    SUPERVISED_AUTONOMY = "supervised_autonomy"


class EvidenceType(StrEnum):
    OBSERVATION = "observation"
    CRAWL_RESULT = "crawl_result"
    GSC = "gsc"
    GA4 = "ga4"
    SERP_RESULT = "serp_result"
    COMPETITOR = "competitor"
    KEYWORD = "keyword"
    CONTENT = "content"
    BRAND = "brand"
    DOCUMENT = "document"
    SOURCE = "source"
    API_DATA = "api_data"
    EXPERIMENT = "experiment"
    HUMAN_INPUT = "human_input"
    MODEL_INFERENCE = "model_inference"
    SYSTEM = "system"


#: Evidence types that represent something the system directly measured.
OBSERVED_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.OBSERVATION,
        EvidenceType.CRAWL_RESULT,
        EvidenceType.GSC,
        EvidenceType.GA4,
        EvidenceType.SERP_RESULT,
        EvidenceType.COMPETITOR,
        EvidenceType.API_DATA,
        EvidenceType.EXPERIMENT,
        EvidenceType.HUMAN_INPUT,
    }
)

#: Evidence types that represent something the system concluded rather than saw.
INFERRED_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.MODEL_INFERENCE,
        EvidenceType.SOURCE,
        EvidenceType.DOCUMENT,
        EvidenceType.KEYWORD,
        EvidenceType.CONTENT,
        EvidenceType.BRAND,
        EvidenceType.SYSTEM,
    }
)


class DataProvenance(StrEnum):
    """How a number reached the user's screen.

    Rule 14 of the build prompt forbids fabricating metrics.  Every metric that
    the platform surfaces carries one of these labels.
    """

    OBSERVED = "observed"
    ESTIMATED = "estimated"
    INFERRED = "inferred"
    USER_PROVIDED = "user_provided"
    SYNTHETIC_DEMO = "synthetic_demo"
    UNKNOWN = "unknown"


class SearchIntent(StrEnum):
    INFORMATIONAL = "informational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"
    NAVIGATIONAL = "navigational"
    LOCAL = "local"
    INVESTIGATIONAL = "investigational"


class CompetitorType(StrEnum):
    BUSINESS = "business_competitor"
    SERP = "serp_competitor"
    CONTENT = "content_competitor"
    LOCAL = "local_competitor"
    PAID = "paid_competitor"


class ContentDecision(StrEnum):
    """The content gap engine must choose exactly one of these."""

    CREATE = "create"
    UPDATE = "update"
    CONSOLIDATE = "consolidate"
    REDIRECT = "redirect"
    DO_NOTHING = "do_nothing"


class ContentAssetType(StrEnum):
    ARTICLE = "article"
    LANDING_PAGE = "landing_page"
    SERVICE_PAGE = "service_page"
    PRODUCT_PAGE = "product_page"
    LOCATION_PAGE = "location_page"
    GUIDE = "guide"
    FAQ = "faq"
    CASE_STUDY = "case_study"
    DERIVATIVE = "derivative"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class RiskCategory(StrEnum):
    GENERAL = "general"
    HEALTH = "health"
    MEDICAL = "medical"
    FINANCIAL = "financial"
    LEGAL = "legal"
    SAFETY = "safety"
    REGULATED = "regulated"


HIGH_RISK_CATEGORIES = frozenset(
    {
        RiskCategory.HEALTH,
        RiskCategory.MEDICAL,
        RiskCategory.FINANCIAL,
        RiskCategory.LEGAL,
        RiskCategory.SAFETY,
        RiskCategory.REGULATED,
    }
)


class SourceTier(StrEnum):
    """Source trust hierarchy (Build Specification section 55)."""

    TIER_1_PRIMARY = "tier_1_primary"
    TIER_2_AUTHORITATIVE = "tier_2_authoritative"
    TIER_3_REPUTABLE_SECONDARY = "tier_3_reputable_secondary"
    TIER_4_INDUSTRY = "tier_4_industry"
    TIER_5_COMMUNITY = "tier_5_community"
    TIER_6_UNVERIFIED = "tier_6_unverified"


SOURCE_TIER_WEIGHT: dict[SourceTier, float] = {
    SourceTier.TIER_1_PRIMARY: 1.0,
    SourceTier.TIER_2_AUTHORITATIVE: 0.85,
    SourceTier.TIER_3_REPUTABLE_SECONDARY: 0.7,
    SourceTier.TIER_4_INDUSTRY: 0.5,
    SourceTier.TIER_5_COMMUNITY: 0.3,
    SourceTier.TIER_6_UNVERIFIED: 0.1,
}


class OpportunityType(StrEnum):
    TECHNICAL_FIX = "technical_fix"
    INDEXABILITY = "indexability"
    ON_PAGE = "on_page"
    CONTENT_CREATE = "content_create"
    CONTENT_UPDATE = "content_update"
    CONTENT_CONSOLIDATE = "content_consolidate"
    INTERNAL_LINKING = "internal_linking"
    STRUCTURED_DATA = "structured_data"
    KEYWORD_GAP = "keyword_gap"
    COMPETITOR_GAP = "competitor_gap"
    CTR_IMPROVEMENT = "ctr_improvement"
    CONVERSION = "conversion"
    LOCAL = "local"
    AI_SEARCH_READINESS = "ai_search_readiness"
    AGENTIC_WEB_READINESS = "agentic_web_readiness"
    PAID_SEARCH = "paid_search"


class OpportunityStatus(StrEnum):
    DETECTED = "detected"
    PRIORITISED = "prioritised"
    RECOMMENDED = "recommended"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    IMPLEMENTED = "implemented"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
    RETRY = "retry"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ActionType(StrEnum):
    CMS_CREATE_DRAFT = "cms.create_draft"
    CMS_UPDATE_DRAFT = "cms.update_draft"
    CMS_PUBLISH = "cms.publish"
    CONTENT_CREATE = "content.create"
    CONTENT_UPDATE = "content.update"
    METADATA_UPDATE = "seo.metadata_update"
    INTERNAL_LINK_ADD = "seo.internal_link_add"
    SCHEMA_UPDATE = "seo.schema_update"
    REDIRECT_CREATE = "seo.redirect_create"
    PAGE_DELETE = "seo.page_delete"
    GSC_SUBMIT_SITEMAP = "gsc.submit_sitemap"
    ADS_CAMPAIGN_CREATE = "ads.campaign_create"
    ADS_BUDGET_CHANGE = "ads.budget_change"
    GBP_UPDATE = "gbp.update"


class CrawlJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IssueSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class SEODimension(StrEnum):
    """Scoring dimensions.  There is deliberately no single opaque `SEO score`."""

    TECHNICAL_HEALTH = "technical_health"
    INDEXABILITY = "indexability"
    CONTENT_QUALITY = "content_quality"
    SEARCH_ALIGNMENT = "search_alignment"
    INTERNAL_LINKING = "internal_linking"
    STRUCTURED_DATA = "structured_data"
    LOCAL_READINESS = "local_readiness"
    AI_SEARCH_READINESS = "ai_search_readiness"
    CONVERSION_READINESS = "conversion_readiness"


class MemoryScope(StrEnum):
    PLATFORM = "platform"
    TENANT = "tenant"
    BRAND = "brand"
    PROJECT = "project"
    MISSION = "mission"
    TASK = "task"


class MemoryType(StrEnum):
    BRAND_FACT = "brand_fact"
    WORKING = "working"
    HISTORICAL = "historical"
    OUTCOME = "outcome"
    LEARNING = "learning"
    PREFERENCE = "preference"


class IntegrationProvider(StrEnum):
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    GOOGLE_ANALYTICS_4 = "google_analytics_4"
    GOOGLE_ADS = "google_ads"
    GOOGLE_BUSINESS_PROFILE = "google_business_profile"
    AHREFS = "ahrefs"
    SEMRUSH = "semrush"
    WORDPRESS = "wordpress"
    WEBFLOW = "webflow"
    GENERIC_CMS = "generic_cms"


class IntegrationMode(StrEnum):
    """Whether a connection talks to the real provider or the dev adapter."""

    PRODUCTION = "production"
    DEVELOPMENT_ADAPTER = "development_adapter"


class IntegrationStatus(StrEnum):
    NOT_CONNECTED = "not_connected"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"
    REVOKED = "revoked"


class ObservationConfidenceClass(StrEnum):
    """AI Search module: never blur these three."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class ContextChannel(StrEnum):
    """Structural separation of the agent context (prompt-injection defence)."""

    SYSTEM = "system"
    DEVELOPER_POLICY = "developer_policy"
    USER = "user"
    TOOL_OUTPUT = "tool_output"
    EXTERNAL_CONTENT = "external_content"


class SynthesisMode(StrEnum):
    """How an agent produced its narrative output."""

    LLM = "llm"
    DETERMINISTIC = "deterministic"
    HYBRID = "hybrid"


__all__ = [
    "HIGH_RISK_CATEGORIES",
    "INFERRED_EVIDENCE_TYPES",
    "OBSERVED_EVIDENCE_TYPES",
    "SOURCE_TIER_WEIGHT",
    "TERMINAL_TASK_STATUSES",
    "ActionStatus",
    "ActionType",
    "AutomationPolicy",
    "CompetitorType",
    "ContentAssetType",
    "ContentDecision",
    "ContentStatus",
    "ContextChannel",
    "CrawlJobStatus",
    "DataProvenance",
    "EvidenceType",
    "IntegrationMode",
    "IntegrationProvider",
    "IntegrationStatus",
    "IssueSeverity",
    "MemoryScope",
    "MemoryType",
    "MissionStatus",
    "ObservationConfidenceClass",
    "OpportunityStatus",
    "OpportunityType",
    "PermissionLevel",
    "RecommendationStatus",
    "RiskCategory",
    "RiskLevel",
    "Role",
    "SEODimension",
    "SearchIntent",
    "SourceTier",
    "SynthesisMode",
    "TaskPriority",
    "TaskStatus",
    "TenantStatus",
    "UserStatus",
]
