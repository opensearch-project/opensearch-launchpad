# Search Quality Evaluation Guide

After successful Phase 4 execution, evaluate the search setup before proceeding to AWS deployment.

## When to Evaluate

Offer evaluation after Phase 4 completes successfully:
> "Would you like to evaluate the search quality? I can analyze relevance, coverage, and capability gaps, and suggest improvements."

If the user declines, skip to Phase 5.

## Evaluation Process

1. **Run test queries** using `opensearch_ops.py search --index <name> --body '<query>'`
2. Design queries that exercise each declared capability (exact match, semantic, fuzzy, structured filters, combined)
3. Score each dimension below based on actual search results
4. Present findings to the user with actionable recommendations

## Scoring Dimensions (1-5)

Score honestly. Do NOT default to high scores. A 5 means genuinely excellent; a 3 means it works but has clear gaps; a 1-2 means it will frustrate users.

### Relevance — do top results match what the user actually meant?

| Score | Criteria |
|-------|----------|
| 5 | Retrieval method matches all query types in the plan (exact, semantic, fuzzy as applicable) |
| 4 | Matches most query types; minor gaps in edge cases |
| 3 | Handles navigational/exact queries but misses intent-based or concept queries |
| 2 | Only works for very precise keyword matches; synonyms and paraphrases fail |
| 1 | Results are largely irrelevant or arbitrary |

### Query Coverage — what fraction of query types are actually handled?

| Score | Criteria |
|-------|----------|
| 5 | All declared capabilities (exact, semantic, structured, fuzzy, combined) are fully supported |
| 4 | Most capabilities supported; one minor gap |
| 3 | Exact and structured work; semantic or fuzzy missing or weak |
| 2 | Only one or two query types work reliably |
| 1 | Coverage is minimal or broken |

### Ranking Quality — are the right documents surfacing at the top?

| Score | Criteria |
|-------|----------|
| 5 | Scoring is meaningful; exact matches rank above partial matches; filters don't pollute scores |
| 4 | Generally good ranking; minor score pollution from structured filters |
| 3 | Ranking works for simple cases but structured filters or fuzzy candidates distort scores |
| 2 | Ranking is largely arbitrary; BM25 TF-IDF scores dominate even for filter-heavy queries |
| 1 | Top results are not the most relevant documents |

### Capability Gap — what important search patterns are completely unsupported?

| Score | Criteria |
|-------|----------|
| 5 | No meaningful gaps given the use case |
| 4 | Minor gap (e.g. no autocomplete) that doesn't affect core use case |
| 3 | One significant gap (e.g. no semantic retrieval for a mixed query workload) |
| 2 | Multiple gaps that will frustrate users regularly |
| 1 | The retrieval method is fundamentally mismatched to the use case |

## Presenting Results

Present findings to the user as:
- **Scores** for each dimension with a one-sentence explanation
- **Issues** — for each issue found, be specific and actionable:
  - Name the dimension it affects
  - Describe exactly what will fail for the user
  - Recommend a concrete fix (see below)
- **Suggested preference changes** — if a different strategy would score meaningfully higher

## Recommended Fixes

Use whichever apply:
- Switch retrieval method (e.g. BM25 to Hybrid, Hybrid to Dense Vector)
- Adjust hybrid weights (e.g. shift lexical-heavy 0.8/0.2 to balanced 0.5/0.5 for more semantic coverage)
- Change embedding model (e.g. swap sparse for dense, or upgrade to a higher-quality model)
- Add or remove sparse encoding (e.g. add neural sparse pipeline for concept queries)
- Tune BM25 parameters (e.g. boost primaryTitle field, move filters to bool.filter to avoid score pollution)
- Add query boosting (e.g. multi_match with field boosts to promote exact title matches)
- Other pipeline or mapping changes that would directly improve the failing query type

## After Evaluation

- If issues are found with `suggested_preferences`, offer to restart from Phase 3 with updated preferences:
  > "Based on the evaluation, I suggest restarting with updated preferences to improve search quality. Would you like to try again?"
- If the user agrees, go back to Phase 3 and apply the suggested preferences.
- If the user declines or scores are acceptable, proceed to Phase 5.
