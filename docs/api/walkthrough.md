# The canonical mission, end to end

This walks the demonstration objective — *"Increase qualified organic leads"* —
from a new account to a set of evidence-backed, approval-gated recommendations.
It matches what `tests/integration/test_mission_workflow.py` asserts.

Set a base URL and (after step 1) a token:

```bash
BASE=http://localhost:8000/api/v1
```

## 1. Register

```bash
curl -s $BASE/auth/register -H 'content-type: application/json' -d '{
  "email": "you@example.com",
  "password": "a-strong-password-123",
  "name": "You",
  "organisation_name": "Your Org"
}'
```

`data.tokens.access_token` is your Bearer token. Export it:

```bash
TOKEN=...   # from the response
AUTH="authorization: Bearer $TOKEN"
```

## 2. Create the brand graph

The brand graph is the one input the system never invents, so this is where the
real business facts go in.

```bash
BRAND=$(curl -s $BASE/brands -H "$AUTH" -H 'content-type: application/json' -d '{
  "name": "Acme Diagnostics", "industry": "diagnostics", "risk_category": "health"
}' | jq -r .data.id)

curl -s $BASE/brands/$BRAND/services -H "$AUTH" -H 'content-type: application/json' -d '{
  "name": "DNA testing", "keywords": ["dna testing", "paternity test"], "revenue_weight": 2.0
}'

curl -s $BASE/brands/$BRAND/competitors -H "$AUTH" -H 'content-type: application/json' -d '{
  "name": "Rival Diagnostics", "domain": "rival.example", "competitor_types": ["serp_competitor"]
}'
```

## 3. Connect the website and the analytics providers

```bash
SITE=$(curl -s $BASE/brands/$BRAND/websites -H "$AUTH" -H 'content-type: application/json' -d '{
  "url": "https://acme.example"
}' | jq -r .data.id)

# With no credentials configured these connect in development-adapter mode and
# the response says so; every figure they later produce is labelled synthetic.
curl -s $BASE/brands/$BRAND/integrations -H "$AUTH" -H 'content-type: application/json' -d '{
  "provider": "google_search_console"
}'
curl -s $BASE/brands/$BRAND/integrations -H "$AUTH" -H 'content-type: application/json' -d '{
  "provider": "google_analytics_4"
}'
```

## 4. Plan the mission

```bash
PLAN=$(curl -s $BASE/brands/$BRAND/missions -H "$AUTH" -H 'content-type: application/json' -d '{
  "objective": "Increase qualified organic leads",
  "website_id": "'$SITE'"
}')
echo "$PLAN" | jq '.data.plan.stages[] | {stage, included, reason}'
MISSION=$(echo "$PLAN" | jq -r .data.mission.id)
```

The plan classifies the objective as `qualified_leads` and selects the stages it
needs. Stages the brand cannot support are returned **excluded, with a reason** —
not hidden. If you had skipped the integrations, `gsc_analysis` and
`ga4_analysis` would show `included: false` with "not connected … nothing has
been estimated in its place".

## 5. Run it

```bash
curl -s -X POST $BASE/missions/$MISSION/run -H "$AUTH"    # 202 Accepted
```

The mission runs in the background through the Agent Runtime, stage by stage.
Poll it:

```bash
curl -s $BASE/missions/$MISSION -H "$AUTH" | jq '{
  status: .data.mission.status,
  baseline: .data.baseline,
  tasks: .data.tasks,
  progress: [.data.progress[] | {stage, status}]
}'
```

Note two things in the result:

- the **baseline** is measured (synthetic-labelled on the development adapter),
  or `null` with a reason if no analytics provider returned one — never a guess;
- the status settles on `monitoring`, not `achieved`. A finished plan is not a
  met objective; achievement is measured against the target metric over time.

## 6. Read the evidence-backed recommendations

```bash
curl -s $BASE/brands/$BRAND/recommendations -H "$AUTH" | jq '.data[] | {
  title, reason, expected_outcome,
  evidence: (.evidence_refs | length),
  approval_required, approval_reason
}'
```

Every recommendation cites evidence (Rule 7). Because the brand is
health-category, content recommendations carry `approval_required: true` with a
reason — nothing publishes itself.

## 7. Approve (the human in the loop)

```bash
REC=...   # a recommendation id from step 6
curl -s -X POST $BASE/recommendations/$REC/approve -H "$AUTH" \
  -H 'content-type: application/json' -d '{"note": "Approved for drafting"}'
```

Approved recommendations become policy-gated actions. A draft can be created;
publishing and any live-site edit still require their own approval before the
execution agent will run them.

## 8. Trace it

Everything above is auditable:

```bash
curl -s "$BASE/agents/runs?mission_id=$MISSION" -H "$AUTH" | jq '.data[] | {agent_id, status, confidence, summary}'
curl -s "$BASE/events?brand_id=$BRAND" -H "$AUTH" | jq '.data[] | {event_type, occurred_at}'
```

Each agent run exposes its observations, evidence, conclusions, confidence and
limitations — never its private reasoning.
