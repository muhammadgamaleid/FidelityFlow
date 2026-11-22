# Measuring Claude usage with FidelityFlow

This directory contains transcript-based measurement tools. They do not call Claude, infer missing token counts, or measure Claude.ai web-chat sessions.

## 1. Capture a baseline and an optimized run

Use the same Claude Code version, model, task, source files, MCP configuration, reasoning effort, and cache conditions. Run the same representative task once without FidelityFlow and once with the feature being evaluated.

Keep the sessions separate. Do not include unrelated requests in either transcript.

Claude Code stores conversation transcripts as JSONL under its local projects directory. Use the actual transcript paths from your environment.

## 2. Read one transcript

```bash
python benchmarks/read_claude_usage.py "/path/to/session.jsonl"
```

The report separates uncached input, cache creation, cache reads, output, and thinking tokens where present. It only counts the usage fields present in the transcript and deduplicates repeated message IDs.

## 3. Compare baseline and optimized runs

```bash
python benchmarks/read_claude_usage.py \
  "/path/to/baseline.jsonl" \
  --compare "/path/to/fidelityflow.jsonl"
```

Machine-readable output:

```bash
python benchmarks/read_claude_usage.py \
  "/path/to/baseline.jsonl" \
  --compare "/path/to/fidelityflow.jsonl" \
  --json
```

The tool reports context-input reduction and observed input-plus-output reduction separately. Cache reads are included in context input because cached content still occupies context; they are not treated as zero tokens.

## 4. Optional API cost calculation

Pricing changes over time and can depend on model, region, cache duration, and provider terms. FidelityFlow intentionally ships no default price table. Supply your own current rates:

```json
{
  "currency": "USD",
  "per_million_tokens": {
    "input_tokens": 0.0,
    "cache_creation_input_tokens": 0.0,
    "cache_read_input_tokens": 0.0,
    "output_tokens": 0.0
  }
}
```

Replace every zero with the applicable current rate before using the estimate. Then run:

```bash
python benchmarks/read_claude_usage.py \
  "/path/to/baseline.jsonl" \
  --compare "/path/to/fidelityflow.jsonl" \
  --pricing "/path/to/current-pricing.json"
```

The resulting cost is an estimate calculated only from your supplied rates. Verify that those rates match the exact model and cache configuration. Thinking tokens are reported only when separately exposed; they are not added as a separate price category because they may already be included in output accounting.

## 5. Evaluate output quality separately

Token telemetry cannot prove that the answer remained correct. Use the same task-specific rubric for both outputs. Score at least:

- Task correctness.
- Evidence and citation fidelity.
- Retrieval recall and source traceability.
- Completeness of requested details, code, formulas, and output format.
- Preservation of failures, warnings, and counter-evidence.

You can attach manually evaluated 0–100 scores:

```bash
python benchmarks/read_claude_usage.py \
  "/path/to/baseline.jsonl" \
  --compare "/path/to/fidelityflow.jsonl" \
  --quality-baseline 95 \
  --quality-candidate 94
```

These scores are printed as manual inputs; the script does not grade responses.

## Important interpretation

- Claude subscription usage limits are not per-token API invoices. Do not turn subscription indicators into dollar savings.
- A smaller character count is not a token measurement.
- Cache creation and cache read reduce or alter billing differently but still occupy context.
- A successful benchmark uses several task categories and repeated runs, not a single example.
- Count extra tool calls, recovery reads, retries, Skills/Plugin overhead, and model-assisted preprocessing in the final evaluation.
- Publish no global saving percentage until a representative test set demonstrates both positive net savings and acceptable task quality.
