#!/usr/bin/env python3
"""Read actual Claude Code token usage and compare baseline/optimized transcripts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

USAGE_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
    "thinking_tokens",
)
COST_FIELDS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def extract_usage(row: dict[str, Any]) -> tuple[str | None, dict[str, int]] | None:
    message = row.get("message")
    message = message if isinstance(message, dict) else {}
    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = row.get("usage")
    if not isinstance(usage, dict):
        return None
    message_id = message.get("id") or row.get("uuid")
    values: dict[str, int] = {}
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if value < 0 or int(value) != value:
            continue
        values[field] = int(value)
    return (str(message_id) if message_id is not None else None, values)


def read_transcript_details(
    path: Path,
) -> tuple[dict[str, int], int, int, dict[str, int]]:
    totals = {field: 0 for field in USAGE_FIELDS}
    seen: set[str] = set()
    model_counts: dict[str, int] = {}
    messages = malformed = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                print(f"warning: skipped invalid JSON on line {line_number}", file=sys.stderr)
                continue
            if not isinstance(row, dict):
                continue
            result = extract_usage(row)
            if result is None:
                continue
            message_id, usage = result
            if message_id is not None:
                if message_id in seen:
                    continue
                seen.add(message_id)
            message = row.get("message")
            message = message if isinstance(message, dict) else {}
            model = message.get("model") or row.get("model")
            if isinstance(model, str) and model:
                model_counts[model] = model_counts.get(model, 0) + 1
            for field, value in usage.items():
                totals[field] += value
            messages += 1
    return totals, messages, malformed, model_counts


def read_transcript(path: Path) -> tuple[dict[str, int], int, int]:
    """Backward-compatible totals helper."""
    totals, messages, malformed, _ = read_transcript_details(path)
    return totals, messages, malformed


def context_input_total(totals: dict[str, int]) -> int:
    return (
        totals["input_tokens"]
        + totals["cache_creation_input_tokens"]
        + totals["cache_read_input_tokens"]
    )


def observed_total(totals: dict[str, int]) -> int:
    return context_input_total(totals) + totals["output_tokens"]


def reduction_percent(baseline: float, candidate: float) -> float | None:
    if baseline <= 0:
        return None
    return (baseline - candidate) / baseline * 100.0


def load_pricing(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read pricing file: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Pricing file must contain a JSON object")
    rates = data.get("per_million_tokens")
    if not isinstance(rates, dict):
        raise ValueError("Pricing file requires a per_million_tokens object")
    normalized: dict[str, float] = {}
    for field in COST_FIELDS:
        value = rates.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"Pricing file requires a non-negative numeric rate for {field}")
        normalized[field] = float(value)
    currency = data.get("currency", "USD")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("Pricing currency must be a non-empty string")
    return {"currency": currency, "per_million_tokens": normalized}


def estimated_api_cost(totals: dict[str, int], pricing: dict[str, Any]) -> float:
    rates = pricing["per_million_tokens"]
    return sum(totals[field] * rates[field] / 1_000_000 for field in COST_FIELDS)


def compare_transcripts(
    baseline: dict[str, int], candidate: dict[str, int]
) -> dict[str, Any]:
    metrics = {}
    for field in USAGE_FIELDS:
        before, after = baseline[field], candidate[field]
        metrics[field] = {
            "baseline": before,
            "candidate": after,
            "difference_candidate_minus_baseline": after - before,
            "reduction_percent": reduction_percent(before, after),
        }
    before_context = context_input_total(baseline)
    after_context = context_input_total(candidate)
    before_total = observed_total(baseline)
    after_total = observed_total(candidate)
    return {
        "metrics": metrics,
        "context_input_tokens": {
            "baseline": before_context,
            "candidate": after_context,
            "difference_candidate_minus_baseline": after_context - before_context,
            "reduction_percent": reduction_percent(before_context, after_context),
        },
        "observed_input_plus_output_tokens": {
            "baseline": before_total,
            "candidate": after_total,
            "difference_candidate_minus_baseline": after_total - before_total,
            "reduction_percent": reduction_percent(before_total, after_total),
        },
        "quality_assessment": (
            "Token telemetry cannot establish answer quality. Evaluate task correctness, "
            "evidence fidelity, retrieval recall, and output completeness separately."
        ),
    }


def format_reduction(value: float | None) -> str:
    return "n/a (baseline is zero)" if value is None else f"{value:.2f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read Claude Code usage or compare baseline and optimized JSONL transcripts."
    )
    parser.add_argument("transcript", type=Path, help="baseline Claude Code JSONL transcript")
    parser.add_argument("--compare", type=Path, help="optimized/candidate transcript")
    parser.add_argument("--pricing", type=Path, help="optional user-supplied API price JSON")
    parser.add_argument("--quality-baseline", type=float)
    parser.add_argument("--quality-candidate", type=float)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    if (args.quality_baseline is None) != (args.quality_candidate is None):
        parser.error("provide both quality scores or neither")
    for field in ("quality_baseline", "quality_candidate"):
        score = getattr(args, field)
        if score is not None and not 0 <= score <= 100:
            parser.error(f"--{field.replace('_', '-')} must be between 0 and 100")
    if args.pricing and not args.compare:
        parser.error("--pricing requires --compare")

    baseline_path = args.transcript.expanduser()
    if not baseline_path.is_file():
        parser.error(f"transcript not found: {baseline_path}")
    try:
        baseline, baseline_messages, baseline_malformed, baseline_models = read_transcript_details(baseline_path)
        report: dict[str, Any] = {
            "baseline": {
                "path": str(baseline_path),
                "messages": baseline_messages,
                "malformed_lines": baseline_malformed,
                "models": baseline_models,
                "usage": baseline,
                "context_input_tokens": context_input_total(baseline),
                "observed_input_plus_output_tokens": observed_total(baseline),
            }
        }
        candidate = None
        if args.compare:
            candidate_path = args.compare.expanduser()
            if not candidate_path.is_file():
                parser.error(f"comparison transcript not found: {candidate_path}")
            candidate, candidate_messages, candidate_malformed, candidate_models = read_transcript_details(candidate_path)
            report["candidate"] = {
                "path": str(candidate_path),
                "messages": candidate_messages,
                "malformed_lines": candidate_malformed,
                "models": candidate_models,
                "usage": candidate,
                "context_input_tokens": context_input_total(candidate),
                "observed_input_plus_output_tokens": observed_total(candidate),
            }
            report["comparison"] = compare_transcripts(baseline, candidate)
            if args.pricing:
                pricing = load_pricing(args.pricing.expanduser())
                base_cost = estimated_api_cost(baseline, pricing)
                candidate_cost = estimated_api_cost(candidate, pricing)
                report["api_cost_estimate"] = {
                    "currency": pricing["currency"],
                    "pricing_source": str(args.pricing.expanduser()),
                    "baseline": base_cost,
                    "candidate": candidate_cost,
                    "difference_candidate_minus_baseline": candidate_cost - base_cost,
                    "reduction_percent": reduction_percent(base_cost, candidate_cost),
                    "note": (
                        "Uses only user-supplied rates. Confirm model, region, cache duration, "
                        "and current provider prices before relying on this estimate."
                    ),
                }
            if args.quality_baseline is not None:
                report["manual_quality_scores"] = {
                    "scale": "0-100, manually assessed; not inferred from token telemetry",
                    "baseline": args.quality_baseline,
                    "candidate": args.quality_candidate,
                    "difference_candidate_minus_baseline": args.quality_candidate - args.quality_baseline,
                }

        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        print(f"transcript: {baseline_path}")
        print(f"messages: {baseline_messages}")
        print(f"malformed_lines: {baseline_malformed}")
        for model, count in sorted(baseline_models.items()):
            print(f"model[{model}]: {count} messages")
        for field in USAGE_FIELDS:
            print(f"{field}: {baseline[field]}")
        print(f"context_input_tokens_including_cache: {context_input_total(baseline)}")
        print(f"observed_input_plus_output_tokens: {observed_total(baseline)}")

        if candidate is not None:
            comparison = report["comparison"]
            print(f"\ncandidate: {args.compare.expanduser()}")
            print("context input reduction: " + format_reduction(comparison["context_input_tokens"]["reduction_percent"]))
            print("input + output reduction: " + format_reduction(comparison["observed_input_plus_output_tokens"]["reduction_percent"]))
            print("\nper-field changes (candidate minus baseline):")
            for field in USAGE_FIELDS:
                metric = comparison["metrics"][field]
                print(
                    f"{field}: {metric['difference_candidate_minus_baseline']} "
                    f"({format_reduction(metric['reduction_percent'])} reduction)"
                )
            if "api_cost_estimate" in report:
                cost = report["api_cost_estimate"]
                print(
                    f"API cost estimate: {cost['baseline']:.8f} -> {cost['candidate']:.8f} "
                    f"{cost['currency']} ({format_reduction(cost['reduction_percent'])} reduction)"
                )
            if "manual_quality_scores" in report:
                quality = report["manual_quality_scores"]
                print(f"manual quality score change: {quality['difference_candidate_minus_baseline']:+.2f} points")
            print("\n" + comparison["quality_assessment"])
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Could not analyze usage: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
