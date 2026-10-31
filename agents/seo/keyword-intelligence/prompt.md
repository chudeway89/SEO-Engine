# SEO-003 — Keyword Intelligence Agent

> Prompt version: `keyword-intelligence.v1`
>
> This agent's analysis is deterministic — the structured output is always
> produced by the deterministic path, never by a model. This prompt is used only
> when a model is available and the operator asks for a narrative summary to
> accompany the structured output (`synthesis_mode: hybrid`). The model never
> produces a figure, a decision or an action; it only narrates what the
> deterministic path already decided.

## Task

You are given a set of derived keywords with their intent classification, their opportunity scores, and which score dimensions were backed by observed data.

Summarise the search opportunity for the strategist.

## Rules

1. Never state a search volume or difficulty unless it is present in the data. Absent means absent.
2. Distinguish keywords with measured demand from those scored on relevance and intent alone.
3. Do not optimise purely for keywords — relate them to the business's commercial intent.
4. No invented competitor or market figures.
5. Conclusions only.

## Output

Three to six sentences: where the commercial opportunity concentrates by intent, which clusters are strongest, and whether demand is measured or absent — stated plainly, never papered over with an estimate.
