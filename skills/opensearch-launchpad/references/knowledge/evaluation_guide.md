# Search Quality Evaluation Guide

Data-driven evaluation that runs real queries against the live index, computes quantitative metrics, and diagnoses issues with actionable recommendations.

## When to Evaluate

Offer evaluation after Phase 4 completes successfully:
> "Would you like to evaluate the search quality? I can run test queries, measure relevance metrics, and suggest improvements."

If the user declines, skip to Phase 5.

## Evaluation Config

The evaluation is driven by a JSON config that defines test queries, expected relevance grades, and methods to compare. Methods are dynamically determined by the previous phase -- whatever search strategies were set up (BM25, hybrid, dense vector, sparse, etc.) become the methods under test.

```json
{
  "index": "my-index",
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "bm25_fields": ["title^4", "text^2"],
  "embedding_field": "combined_embedding",
  "embedded_fields": "title + text",
  "title_field": "primaryTitle",
  "k": 5,
  "methods": [
    {"name": "Hybrid", "mode": "hybrid", "tag": "hybrid"},
    {"name": "BM25", "mode": "bm25", "tag": "lexical"},
    {"name": "KNN", "mode": "knn", "tag": "vector"}
  ],
  "tests": [
    {
      "name": "Q1: Exact title lookup",
      "type": "exact",
      "query": "The Matrix",
      "relevance": {"The Matrix": 3, "The Matrix Reloaded": 2}
    },
    {
      "name": "Q2: Semantic concept query",
      "type": "semantic",
      "query": "movies about artificial intelligence",
      "relevance": {"The Matrix": 3, "Ex Machina": 3, "A.I.": 2}
    }
  ]
}
```

### Config Fields

| Field | Required | Description |
|-------|----------|-------------|
| `index` | Yes | OpenSearch index name |
| `model` | Yes | SentenceTransformer model for embedding queries |
| `bm25_fields` | Yes | Fields for BM25 multi_match (with optional boosts) |
| `embedding_field` | No | KNN vector field name (default: `combined_embedding`) |
| `title_field` | No | Field used to match relevance judgments (default: `title`) |
| `k` | No | Cutoff depth for metrics (default: `5`) |
| `methods` | No | List of methods to evaluate (default: HYBRID/BM25/KNN) |
| `tests` | Yes | Test queries with graded relevance judgments |

### Method Config

Each method has:
- `name`: Display name (any string)
- `mode`: Search mode (`bm25`, `knn`, `hybrid`) for the CLI
- `tag` (optional): Category for smarter diagnosis -- `lexical`, `vector`, `hybrid`, `sparse`, `combined`

Methods are not limited to three. Add as many as the setup requires.

### Relevance Grades

| Grade | Meaning |
|-------|---------|
| 3 | Perfect -- this is the ideal result for this query |
| 2 | Relevant -- clearly useful to the searcher |
| 1 | Marginal -- related but not what was intended |
| 0 | Irrelevant (default for unlisted documents) |

## Metrics

Three metrics are computed per query per method, all at cutoff `k`:

| Metric | Formula | What it measures |
|--------|---------|------------------|
| **nDCG@k** | Normalized Discounted Cumulative Gain | Ranking quality -- are the best docs at the top? |
| **P@k** | Precision at k | What fraction of top-k results are relevant? |
| **MRR** | Mean Reciprocal Rank | How quickly does the first relevant result appear? |

### Target Thresholds

| Metric | Good (>= ) | Acceptable (>=) | Poor (<) |
|--------|-----------|-----------------|----------|
| Mean nDCG@k | 0.70 | 0.50 | 0.30 |
| Mean P@k | 0.60 | 0.40 | 0.20 |
| Mean MRR | 0.70 | 0.50 | 0.20 |

## Diagnosis Rules

The engine applies five diagnostic rules, comparing across all provided methods:

### Rule 1: All methods fail (nDCG < 0.3 for every method)
- **Severity**: HIGH
- **Meaning**: No retrieval strategy can find relevant documents for this query
- **Tag**: `[MODEL_SELECTION]` for semantic queries, `[INDEX_MAPPING]` for combined/structured
- **Fix**: Check field mappings, analyzers, or upgrade embedding model

### Rule 2: Pairwise method gaps (tag-aware)
- **Severity**: MEDIUM
- **Triggers when**: A vector-tagged method fails (nDCG < 0.3) while a lexical-tagged method succeeds (nDCG > 0.5), or vice versa
- **Tag**: `[MODEL_SELECTION]` when vector fails, `[INDEX_MAPPING]` when lexical fails
- **Fix**: Upgrade embedding model, or add proper text analyzers/boosting

### Rule 3: Hybrid worse than single signals
- **Severity**: MEDIUM/LOW
- **Triggers when**: A hybrid-tagged method's nDCG is > 0.15 below the best non-hybrid method
- **Tag**: `[SEARCH_PIPELINE]`
- **Fix**: Adjust hybrid weights, or use query-type-aware routing

### Rule 4: Irrelevant docs in top-2
- **Severity**: MEDIUM
- **Triggers when**: An irrelevant document (grade 0) appears in positions 1-2 and nDCG < 0.8
- **Tag**: `[QUERY_TUNING]` or `[MODEL_SELECTION]`
- **Fix**: Reduce field boosts, restructure query, or upgrade model

### Rule 5: Missed relevant documents
- **Severity**: LOW
- **Triggers when**: High-relevance documents (grade >= 2) don't appear in any method's top-k
- **Tag**: `[MODEL_SELECTION]`
- **Fix**: Embed more fields, use a higher-capacity model

## Finding Tags

| Tag | What it targets | Example fix |
|-----|----------------|-------------|
| `[INDEX_MAPPING]` | Field types, analyzers, `.keyword` sub-fields | Add `.keyword` to filterable fields |
| `[EMBEDDING_FIELDS]` | Which fields are embedded | Concatenate `title + genres` before embedding |
| `[MODEL_SELECTION]` | Embedding model quality/type | Switch from sparse to dense, or upgrade model size |
| `[SEARCH_PIPELINE]` | Hybrid weights, normalization | Shift from 0.8/0.2 to 0.5/0.5 balanced |
| `[QUERY_TUNING]` | Field boosts, fuzziness, filter placement | Move filters to `bool.filter` to avoid score pollution |

## Completion Criteria

The evaluation passes if **any** of:
- Mean nDCG@k across all methods > 0.7
- All findings are LOW severity only
- No HIGH severity findings and setup matches the use case

## Running Evaluation

### CLI
```bash
uv run --with opensearch-py --with sentence-transformers \
    python scripts/evaluate.py --config path/to/config.json --k 5
```

### As library (from other scripts or the agent)
```python
from lib.evaluate import evaluate_results, format_report

report = evaluate_results(
    tests=tests,
    results_by_method={"Hybrid": [resp1, ...], "BM25": [resp1, ...]},
    k=5,
    title_field="primaryTitle",
    method_tags={"Hybrid": "hybrid", "BM25": "lexical"},
)
print(format_report(report, config={"index": "my-index"}))
```

The `results_by_method` dict accepts pre-computed OpenSearch search responses, so callers can use any search mechanism (SentenceTransformer, neural search pipeline, custom queries, etc.).

## After Evaluation

- If HIGH findings exist, offer to restart from Phase 3 with updated preferences:
  > "Based on the evaluation, I suggest [specific fix]. Would you like to restart with updated preferences?"
- If only LOW findings, proceed to Phase 5.
- If the user wants to iterate, update the config and re-run.
