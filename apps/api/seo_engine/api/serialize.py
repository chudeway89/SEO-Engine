"""Row → response serialisation.

One place, so every router presents the same shape for the same thing and no
router ever leaks a column by accident. Credential material, password hashes
and raw provider payloads have no serialiser at all — they cannot be returned
because nothing here knows how.
"""

from __future__ import annotations

from typing import Any


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def tenant(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "status": row.status,
        "created_at": _iso(row.created_at),
    }


def user(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "email": row.email,
        "name": row.name,
        "status": row.status,
    }


def membership(row: Any, member: Any | None = None) -> dict[str, Any]:
    data = {
        "user_id": str(row.user_id),
        "role": str(row.role),
        "is_default": row.is_default,
    }
    if member is not None:
        data["user"] = user(member)
    return data


def tokens(issued: Any) -> dict[str, Any]:
    return {
        "access_token": issued.access_token,
        "refresh_token": issued.refresh_token,
        "token_type": issued.token_type,
        "expires_in": issued.expires_in,
    }


def brand(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "slug": row.slug,
        "description": row.description,
        "industry": row.industry,
        "website": row.website,
        "country": row.country,
        "primary_language": row.primary_language,
        "business_model": row.business_model,
        "risk_category": row.risk_category,
        "created_at": _iso(row.created_at),
    }


def brand_profile(profile: dict[str, Any]) -> dict[str, Any]:
    b = profile["brand"]
    return {
        "brand": brand(b),
        "goals": [
            {
                "id": str(g.id),
                "goal_type": g.goal_type,
                "description": g.description,
                "target_metric": g.target_metric,
                "target_value": g.target_value,
                "timeframe": g.timeframe,
                "priority": g.priority,
                "status": g.status,
            }
            for g in profile["goals"]
        ],
        "services": [
            {
                "id": str(s.id),
                "name": s.name,
                "description": s.description,
                "category": s.category,
                "keywords": s.keywords,
                "landing_url": s.landing_url,
                "priority": s.priority,
                "revenue_weight": s.revenue_weight,
            }
            for s in profile["services"]
        ],
        "products": [
            {"id": str(p.id), "name": p.name, "description": p.description, "category": p.category}
            for p in profile["products"]
        ],
        "audiences": [
            {
                "id": str(a.id),
                "name": a.name,
                "description": a.description,
                "pains": a.pains,
                "goals": a.goals,
                "vocabulary": a.vocabulary,
                "stage": a.stage,
                "priority": a.priority,
            }
            for a in profile["audiences"]
        ],
        "locations": [
            {
                "id": str(location.id),
                "name": location.name,
                "country": location.country,
                "region": location.region,
                "city": location.city,
                "is_primary": location.is_primary,
            }
            for location in profile["locations"]
        ],
        "competitors": [competitor(c) for c in profile["competitors"]],
        "voice": (
            {
                "tone": profile["voice"].tone,
                "reading_level": profile["voice"].reading_level,
                "person": profile["voice"].person,
                "approved_terminology": profile["voice"].approved_terminology,
                "forbidden_terminology": profile["voice"].forbidden_terminology,
                "style_rules": profile["voice"].style_rules,
            }
            if profile["voice"]
            else None
        ),
        "claims": [claim(c) for c in profile["claims"]],
        "prohibited_claims": [claim(c) for c in profile["prohibited_claims"]],
    }


def claim(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "claim": row.claim,
        "source": row.source,
        "risk": row.risk,
        "status": row.status,
        "is_prohibited": row.is_prohibited,
    }


def competitor(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "domain": row.domain,
        "competitor_types": row.competitor_types,
        "priority": row.priority,
        "discovered_via": row.discovered_via,
        "observations": row.observations or {},
    }


def website(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "brand_id": str(row.brand_id),
        "domain": row.domain,
        "base_url": row.base_url,
        "cms": row.cms,
        "crawl_frequency": row.crawl_frequency,
        "last_crawled_at": _iso(row.last_crawled_at),
        "created_at": _iso(row.created_at),
    }


def crawl_job(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "website_id": str(row.website_id),
        "status": row.status,
        "pages_crawled": row.pages_crawled,
        "pages_discovered": row.pages_discovered,
        "errors_count": row.errors_count,
        "stopped_reason": row.stopped_reason,
        "trigger": row.trigger,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
    }


def page(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "url": row.url,
        "path": row.path,
        "status_code": row.status_code,
        "title": row.title,
        "meta_description": row.meta_description,
        "canonical_url": row.canonical_url,
        "h1": row.h1,
        "word_count": row.word_count,
        "indexability": row.indexability,
        "indexability_reason": row.indexability_reason,
        "last_crawled_at": _iso(row.last_crawled_at),
    }


def issue(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "check_id": row.check_id,
        "title": row.title,
        "severity": row.severity,
        "dimension": row.dimension,
        "url": row.url,
        "detail": row.detail,
        "recommendation": row.recommendation,
        "status": row.status,
    }


def scorecard(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "website_id": str(row.website_id),
        "overall": row.overall,
        "dimensions": row.dimensions,
        "issues_total": row.issues_total,
        "pages_evaluated": row.pages_evaluated,
        "created_at": _iso(row.created_at),
    }


def keyword(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "keyword": row.keyword,
        "normalised": row.normalised,
        "primary_intent": row.primary_intent,
        "intent": row.intent,
        "opportunity_score": row.opportunity_score,
        "score_breakdown": row.score_breakdown,
        "is_branded": row.is_branded,
        "is_local": row.is_local,
        "is_question": row.is_question,
        "mapped_url": row.mapped_url,
        "cluster_id": str(row.cluster_id) if row.cluster_id else None,
        "source": row.source,
    }


def keyword_cluster(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "label": row.label,
        "head_keyword": row.head_keyword,
        "keyword_count": row.keyword_count,
        "intent": row.intent,
        "opportunity_score": row.opportunity_score,
        "recommended_decision": row.recommended_decision,
    }


def mission(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "brand_id": str(row.brand_id),
        "objective": row.objective,
        "mission_type": row.mission_type,
        "status": row.status,
        "target_metric": row.target_metric,
        "target_value": row.target_value,
        "baseline": row.baseline,
        "baseline_provenance": row.baseline_provenance,
        "baseline_source": row.baseline_source,
        "automation_policy": row.automation_policy,
        "plan_summary": row.plan_summary,
        "strategy": row.strategy or {},
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def mission_progress(row: Any) -> dict[str, Any]:
    return {
        "stage": row.stage,
        "status": row.status,
        "detail": row.detail,
        "percent_complete": row.percent_complete,
        "at": _iso(row.created_at),
    }


def mission_metric(row: Any) -> dict[str, Any]:
    return {
        "metric": row.metric,
        "value": row.value,
        "unit": row.unit,
        "provenance": row.provenance,
        "source": row.source,
        "observed_at": _iso(row.observed_at),
    }


def agent_run(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "agent_id": row.agent_id,
        "agent_version": row.agent_version,
        "status": row.status,
        "objective": row.objective,
        "summary": row.summary,
        "confidence": row.confidence,
        "synthesis_mode": row.synthesis_mode,
        "limitations": row.limitations or [],
        "security_flags": row.security_flags or [],
        "mission_id": str(row.mission_id) if row.mission_id else None,
        "brand_id": str(row.brand_id) if row.brand_id else None,
        "error_code": row.error_code,
        "latency_ms": row.latency_ms,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
    }


def opportunity(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "opportunity_type": row.opportunity_type,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority_score": row.priority_score,
        "business_impact": row.business_impact,
        "seo_impact": row.seo_impact,
        "effort": row.effort,
        "confidence": row.confidence,
        "risk": row.risk,
        "strategic_fit": row.strategic_fit,
        "target_url": row.target_url,
        "evidence_refs": row.evidence_refs or [],
        "priority_breakdown": row.priority_breakdown or {},
        "detected_by": row.detected_by_agent,
        "created_at": _iso(row.created_at),
    }


def recommendation(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "recommendation_type": row.recommendation_type,
        "title": row.title,
        "problem": row.problem,
        "opportunity": row.opportunity_statement,
        "reason": row.reason,
        "expected_outcome": row.expected_outcome,
        "status": row.status,
        "priority_score": row.priority_score,
        "business_impact": row.business_impact,
        "seo_impact": row.seo_impact,
        "effort": row.effort,
        "risk": row.risk,
        "confidence": row.confidence,
        "is_hypothesis": row.is_hypothesis,
        "evidence_refs": row.evidence_refs or [],
        "approval_required": row.approval_required,
        "approval_reason": row.approval_reason,
        "proposed_action": row.proposed_action,
        "decided_by": str(row.decided_by) if row.decided_by else None,
        "decided_at": _iso(row.decided_at),
        "decision_note": row.decision_note,
        "created_at": _iso(row.created_at),
    }


def action(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action_type": row.action_type,
        "status": row.status,
        "target": row.target or {},
        "risk": row.risk,
        "approval_required": row.approval_required,
        "approved_by": str(row.approved_by) if row.approved_by else None,
        "approved_at": _iso(row.approved_at),
        "executed_at": _iso(row.executed_at),
        "integration_mode": row.integration_mode,
        "provider": row.provider,
        "result": row.result or {},
        "error_message": row.error_message,
        "policy_decision": row.policy_decision or {},
        "recommendation_id": str(row.recommendation_id) if row.recommendation_id else None,
        "created_at": _iso(row.created_at),
    }


def integration_connection(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "status": row.status,
        "mode": row.mode,
        "capabilities": row.capabilities or [],
        "settings": {
            key: value
            for key, value in (row.settings or {}).items()
            # Connection settings may name external properties; they never
            # contain credentials, but be deliberate about what goes out.
            if key in {"site_url", "property_id", "account", "notice"}
        },
        "account_label": row.account_label,
        "connected_at": _iso(row.created_at),
    }


def memory_hit(hit: Any) -> dict[str, Any]:
    row = hit.memory
    return {
        "id": str(row.id),
        "key": row.key,
        "content": row.content,
        "scope": row.scope,
        "memory_type": row.memory_type,
        "importance": row.importance,
        "confidence": row.confidence,
        "source": row.source,
        "similarity": hit.similarity,
        "created_at": _iso(row.created_at),
    }


def event(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "event_ref": row.event_ref,
        "event_type": row.event_type,
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "correlation_id": row.correlation_id,
        "payload": row.payload,
        "occurred_at": _iso(row.occurred_at),
    }


def audit_log(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "actor_id": row.actor_id,
        "actor_label": row.actor_label,
        "outcome": row.outcome,
        "reason": row.reason,
        "request_id": row.request_id,
        "correlation_id": row.correlation_id,
        "at": _iso(row.created_at),
    }


def evidence_row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "ref": row.ref,
        "evidence_type": row.evidence_type,
        "source": row.source,
        "source_ref": row.source_ref,
        "observation": row.observation,
        "data": row.structured_data or {},
        "is_observation": row.is_observation,
        "provenance": row.provenance,
        "confidence": row.confidence,
        "agent_id": row.agent_id,
        "observed_at": _iso(row.observed_at),
    }


def content_asset(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "brand_id": str(row.brand_id),
        "title": row.title,
        "asset_type": row.asset_type,
        "slug": row.slug,
        "url": row.url,
        "status": row.status,
        "risk_category": row.risk_category,
        "current_version": row.current_version,
        "primary_keyword": row.primary_keyword,
        "external_ref": row.external_ref or {},
        "is_synthetic": row.is_synthetic,
        "published_at": _iso(row.published_at),
        "created_at": _iso(row.created_at),
    }


def content_version(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "version": row.version,
        "title": row.title,
        "meta_description": row.meta_description,
        "body_markdown": row.body_markdown,
        "word_count": row.word_count,
        "change_summary": row.change_summary,
        "synthesis_mode": row.synthesis_mode,
        "created_by_agent": row.created_by_agent,
        "brief_id": str(row.brief_id) if row.brief_id else None,
        "created_at": _iso(row.created_at),
    }


def content_evaluation(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "content_version_id": str(row.content_version_id) if row.content_version_id else None,
        "evaluation_type": row.evaluation_type,
        "overall_score": row.overall_score,
        "passed": row.passed,
        "criteria": row.criteria,
        "blocking_failures": row.blocking_failures,
        "warnings": row.warnings,
        "requires_human_review": row.requires_human_review,
        "evaluated_by_agent": row.evaluated_by_agent,
        "created_at": _iso(row.created_at),
    }


def content_repair(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "issue": row.issue,
        "repair_type": row.repair_type,
        "detail": row.detail,
        "applied": row.applied,
        "performed_by_agent": row.performed_by_agent,
    }


def content_representation(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "platform": row.platform,
        "audience": row.audience,
        "objective": row.objective,
        "format": row.format,
        "tone": row.tone,
        "cta": row.cta,
        "body": row.body,
        "canonical_source_url": row.canonical_source_url,
        "status": row.status,
    }
