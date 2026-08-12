"""Internal event contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from seo_engine.shared.ids import new_ref, utcnow


class EventType:
    """Canonical event names (Build Prompt "Event model" + Architecture Pack §32)."""

    BRAND_CREATED = "BrandCreated"
    BRAND_UPDATED = "BrandUpdated"
    WEBSITE_ADDED = "WebsiteAdded"
    WEBSITE_CONNECTED = "WebsiteConnected"
    CRAWL_STARTED = "CrawlStarted"
    CRAWL_COMPLETED = "CrawlCompleted"
    CRAWL_FAILED = "CrawlFailed"
    TECHNICAL_AUDIT_COMPLETED = "TechnicalAuditCompleted"
    AUDIT_STARTED = "AuditStarted"
    AUDIT_COMPLETED = "AuditCompleted"
    KEYWORD_RESEARCH_STARTED = "KeywordResearchStarted"
    KEYWORD_RESEARCH_COMPLETED = "KeywordResearchCompleted"
    COMPETITOR_DISCOVERED = "CompetitorDiscovered"
    COMPETITOR_ANALYSIS_COMPLETED = "CompetitorAnalysisCompleted"
    CONTENT_GAP_DETECTED = "ContentGapDetected"
    OPPORTUNITY_DETECTED = "OpportunityDetected"
    OPPORTUNITY_PRIORITISED = "OpportunityPrioritised"
    RECOMMENDATION_CREATED = "RecommendationCreated"
    RECOMMENDATION_APPROVED = "RecommendationApproved"
    RECOMMENDATION_REJECTED = "RecommendationRejected"
    ACTION_CREATED = "ActionCreated"
    ACTION_APPROVED = "ActionApproved"
    ACTION_EXECUTED = "ActionExecuted"
    ACTION_FAILED = "ActionFailed"
    CONTENT_BRIEF_CREATED = "ContentBriefCreated"
    CONTENT_CREATED = "ContentCreated"
    CONTENT_UPDATED = "ContentUpdated"
    CONTENT_REVIEWED = "ContentReviewed"
    CONTENT_PUBLISHED = "ContentPublished"
    TECHNICAL_ISSUE_DETECTED = "TechnicalIssueDetected"
    ANALYTICS_SYNCED = "AnalyticsSynced"
    ANOMALY_DETECTED = "AnomalyDetected"
    OUTCOME_RECORDED = "OutcomeRecorded"
    MEMORY_CREATED = "MemoryCreated"
    LEARNING_CREATED = "LearningCreated"
    MISSION_CREATED = "MissionCreated"
    MISSION_PLANNED = "MissionPlanned"
    MISSION_PROGRESSED = "MissionProgressed"
    MISSION_COMPLETED = "MissionCompleted"
    TASK_CREATED = "TaskCreated"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    AGENT_RUN_STARTED = "AgentRunStarted"
    AGENT_RUN_COMPLETED = "AgentRunCompleted"
    AGENT_RUN_FAILED = "AgentRunFailed"
    PROMPT_INJECTION_DETECTED = "PromptInjectionDetected"
    POLICY_BLOCKED_ACTION = "PolicyBlockedAction"


class DomainEvent(BaseModel):
    """Immutable event envelope."""

    event_id: str = Field(default_factory=lambda: new_ref("evt"))
    event_type: str
    tenant_id: UUID
    brand_id: UUID | None = None
    aggregate_type: str = "system"
    aggregate_id: str | None = None
    entity_id: str | None = None
    actor_type: str = "system"
    actor_id: str | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    correlation_id: str = Field(default_factory=lambda: new_ref("corr"))
    causation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1


__all__ = ["DomainEvent", "EventType"]
